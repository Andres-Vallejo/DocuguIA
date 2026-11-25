from datetime import date
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import MAX_KEY_LENGTH, ROOT, Settings
from .ingest import MAX_BYTES, extract
from .qa import ProviderError, answer
from .rendering import prepare_document, render_docx_pdf, save_local_files
from .store import Store

STATES = {"current", "historical", "draft"}


def valid_category(value):
    """Keep the existing `block` API field while allowing categories for any topic."""
    return 1 <= len(value) <= 80 and value == value.strip() and value.casefold() != "all" and all(c.isprintable() for c in value)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    block: str = "all"
    status: str = "active"
    mode: str = "local"


class DocumentUpdate(BaseModel):
    status: str
    allow_cloud: bool


def create_app(settings=None, provider=None, converter=render_docx_pdf):
    settings = settings or Settings()
    store = Store(settings.db)
    app = FastAPI(title="DocuguIA", version="0.2.0")
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_access(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme:
                    return JSONResponse({"detail": "La operación debe realizarse desde la aplicación local."}, status_code=403)
            try:
                if int(request.headers.get("content-length", "0")) > MAX_BYTES + 100_000:
                    return JSONResponse({"detail": "Archivo demasiado grande: máximo 10 MB."}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Tamaño de solicitud no válido."}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "app/static/index.html")

    @app.get("/api/status")
    def status():
        config = settings.runtime()
        return {"key_configured": bool(config["api_key"]), "free_confirmed": config["free_confirmed"],
                "model": config["model"], "model_allowed": config["model_allowed"],
                "daily_limit": config["daily_limit"], "calls_today": store.usage(),
                "documents": len(store.documents()), "storage": "local", "version": "0.2.0"}

    @app.post("/api/settings")
    async def save_settings(request: Request):
        # Avoid validation error payloads reflecting secrets into the browser.
        try:
            raw = await request.body()
            if len(raw) > MAX_KEY_LENGTH + 1024:
                raise ValueError("Configuración demasiado grande.")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("api_key"), str):
                raise ValueError("Configuración no válida.")
        except (ValueError, TypeError):
            raise HTTPException(400, "La configuración no es válida. Pega únicamente la clave y confirma la casilla Free.") from None
        try:
            settings.save_key(payload["api_key"].strip(), payload.get("free_confirmed") is True)
        except ValueError as exc:
            # save_key only raises fixed messages; never reflects the supplied key.
            raise HTTPException(400, str(exc)) from None
        except OSError:
            raise HTTPException(503, "No se pudo guardar la clave en el archivo local. Comprueba los permisos de la carpeta de DocuguIA.") from None
        return {"saved": True, "message": "Clave guardada en .env local. No se ha enviado ninguna consulta a Google."}

    @app.get("/api/documents")
    def documents():
        docs = store.documents()
        groups = {}
        for doc in docs:
            if doc["status"] == "current":
                groups.setdefault((doc["family"], doc["block"]), []).append(doc["id"])
        conflicts = [{"family": k[0], "block": k[1], "documents": v} for k, v in groups.items() if len(v) > 1]
        categories = sorted({"general", *(doc["block"] for doc in docs)}, key=str.casefold)
        return {"documents": docs, "version_warnings": conflicts, "categories": categories}

    @app.post("/api/documents")
    async def upload(file: UploadFile = File(...), title: str = Form(...), family: str = Form(""),
                     version: str = Form("1"), document_date: str = Form(""), block: str = Form("general"),
                     status: str = Form("draft"), allow_cloud: bool = Form(False)):
        title, family, version, block = title.strip(), family.strip(), version.strip(), block.strip()
        if not 1 <= len(title) <= 180 or len(family) > 120 or not 1 <= len(version) <= 60:
            raise HTTPException(400, "Comprueba el título, la familia y la versión.")
        if not valid_category(block) or status not in STATES:
            raise HTTPException(400, "La categoría debe tener de 1 a 80 caracteres visibles y no puede llamarse «all». Comprueba también el estado.")
        try:
            if document_date:
                date.fromisoformat(document_date)
            filename = (file.filename or "documento").replace("\\", "/").split("/")[-1][:180]
            content = await file.read(MAX_BYTES + 1)
            chunks, warnings, preview = prepare_document(filename, content, settings.data_dir, converter)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        finally:
            await file.close()
        meta = {"title": title, "family": family or title, "version": version, "document_date": document_date,
                "block": block, "status": status, "allow_cloud": allow_cloud}
        docid, created = store.add(filename, content, meta, chunks, warnings)
        save_local_files(settings.data_dir, docid, filename, content, preview)
        return {"id": docid, "created": created, "warnings": warnings, "chunks": len(chunks)}

    @app.get('/api/documents/{docid}/preview')
    def preview_document(docid: str):
        import re
        if not re.fullmatch(r'[0-9a-f]{32}', docid):
            raise HTTPException(404, 'Documento no encontrado.')
        with store.connect() as db:
            document = db.execute('SELECT id FROM documents WHERE id=?', (docid,)).fetchone()
        preview = settings.data_dir / 'previews' / (docid + '.pdf')
        if not document or not preview.is_file():
            raise HTTPException(404, 'Este documento todavía no tiene una copia PDF local.')
        return FileResponse(preview, media_type='application/pdf', content_disposition_type='inline')

    @app.patch("/api/documents/{docid}")
    def update(docid: str, payload: DocumentUpdate):
        if payload.status not in STATES:
            raise HTTPException(400, "Estado no válido.")
        if not store.update(docid, payload.status, payload.allow_cloud):
            raise HTTPException(404, "Documento no encontrado.")
        return {"updated": True}

    @app.delete("/api/documents/{docid}")
    def delete(docid: str):
        if not store.delete(docid):
            raise HTTPException(404, "Documento no encontrado.")
        for directory in ('originals', 'previews'):
            for saved in (settings.data_dir / directory).glob(docid + '.*'):
                saved.unlink(missing_ok=True)
        return {"deleted": True}

    @app.post("/api/demo")
    def demo():
        manifest = json.loads((ROOT / "demo/manifest.json").read_text(encoding="utf-8"))
        count = 0
        for item in manifest:
            content = (ROOT / "demo" / item["file"]).read_bytes()
            chunks, warnings = extract(item["file"], content)
            _, created = store.add(item["file"], content, item, chunks, warnings)
            count += created
        return {"added": count, "message": "Documentos ficticios cargados. No contienen datos institucionales."}

    @app.post("/api/ask")
    def ask(payload: Question):
        if (payload.block != "all" and not valid_category(payload.block)) or payload.status not in STATES | {"all", "active"} or payload.mode not in {"local", "gemini"}:
            raise HTTPException(400, "Filtros o modo no válido.")
        try:
            return answer(store, settings, payload.question, payload.block, payload.status, payload.mode, provider)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from None

    app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
    return app


app = create_app()
