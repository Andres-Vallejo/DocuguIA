from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import time
from zipfile import ZipFile

from fastapi.testclient import TestClient
import httpx
import pytest
from pypdf import PdfWriter

from app.config import Settings
from app.ingest import CHUNK_SIZE, MAX_BYTES, extract, pack_paragraphs
from app.main import create_app
from app.qa import ProviderError, answer, call_gemini, validate_answer
from app.store import Store


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL", "GEMINI_FREE_TIER_CONFIRMED",
                 "MAX_GEMINI_CALLS_PER_DAY", "MIN_GEMINI_INTERVAL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(root=tmp_path)
    app = create_app(settings, converter=None)
    client = TestClient(app)
    client.post("/api/demo").raise_for_status()
    return client, app.state.store, settings


def test_demo_is_idempotent_and_does_not_send_requests(setup):
    client, store, settings = setup
    assert len(store.documents()) == 6
    assert client.post("/api/demo").json()["added"] == 0
    assert store.usage() == 0
    assert not settings.runtime()["api_key"]


def test_version_filters_never_mix_default_with_history(setup):
    _, store, _ = setup
    current = store.retrieve("pruebas aceptación inalámbrica", "1", "current")
    historical = store.retrieve("pruebas aceptación inalámbrica", "1", "historical")
    assert "redes_actual.md" in {s["filename"] for s in current}
    assert "redes_historico.md" not in {s["filename"] for s in current}
    assert {s["filename"] for s in historical} == {"redes_historico.md"}


def test_block_filter_and_no_match(setup):
    client, store, _ = setup
    assert "redes_actual.md" not in {s["filename"] for s in store.retrieve("equipos red", "2")}
    response = client.post("/api/ask", json={"question": "ZXQJ-998877", "mode": "gemini"})
    assert response.json()["status"] == "insufficient"
    assert store.usage() == 0


def test_cloud_opt_in_is_enforced_before_prompt(setup):
    client, store, settings = setup
    client.post("/api/documents", files={"file": ("privado.txt", b"La clave marcadora secretolocal indica una obra privada.")},
                data={"title": "Privado", "status": "current"}).raise_for_status()
    assert store.retrieve("secretolocal")
    assert not store.retrieve("secretolocal", cloud=True)
    result = answer(store, settings, "secretolocal", "all", "current", "gemini", provider=lambda *_: pytest.fail("Se filtró un documento privado"))
    assert result["status"] == "cloud_permission_required"
    assert store.usage() == 0


def test_upload_delete_and_cache_invalidation(setup):
    client, store, _ = setup
    response = client.post("/api/documents", files={"file": ("../unico.txt", "Marcador borralocal con evidencia suficiente para probar eliminación.".encode())}, data={"title": "Prueba", "status": "current"})
    docid = response.json()["id"]
    store.cache("probe", {"ok": True})
    assert store.retrieve("borralocal")[0]["filename"] == "unico.txt"
    client.delete("/api/documents/" + docid).raise_for_status()
    assert not store.retrieve("borralocal")
    assert store.cached("probe") is None


def test_duplicate_current_family_is_visible(setup):
    client, _, _ = setup
    client.post("/api/documents", files={"file": ("otra.txt", b"Contenido alternativo del anexo de redes para demostrar conflicto.")}, data={"title": "Otra actual", "family": "demo-redes", "version": "3", "block": "1", "status": "current"}).raise_for_status()
    assert client.get("/api/documents").json()["version_warnings"][0]["family"] == "demo-redes"


def test_unknown_filters_and_invalid_upload_rejected(setup):
    client, _, _ = setup
    assert client.post("/api/ask", json={"question": "Pregunta válida", "block": "x" * 81}).status_code == 400
    assert client.post("/api/documents", files={"file": ("x.exe", b"binary")}, data={"title": "x"}).status_code == 400
    assert client.post("/api/documents", files={"file": ("x.txt", b"valid sample text long enough")}, data={"title": "x", "document_date": "hoy"}).status_code == 400


def test_key_stays_local_and_not_in_any_response(setup):
    client, _, settings = setup
    fake = "TEST_ONLY_NOT_A_REAL_KEY_123456789"
    response = client.post("/api/settings", json={"api_key": fake, "free_confirmed": True})
    assert response.status_code == 200
    assert settings.runtime()["api_key"] == fake
    assert fake not in response.text + client.get("/api/status").text
    invalid = client.post("/api/settings", json={"api_key": fake, "free_confirmed": False})
    assert invalid.status_code == 400 and fake not in invalid.text


def test_cross_origin_and_external_hosts_cannot_save_keys(setup):
    client, _, _ = setup
    assert client.post("/api/settings", headers={"origin": "https://evil.example"}, json={}).status_code == 403
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400


def test_long_auth_key_with_dots_round_trips_without_being_reflected(setup):
    client, _, settings = setup
    fake = "AQ." + "SYNTHETIC_NOT_A_CREDENTIAL_" * 40 + ".-_=test"
    assert len(fake) > 256
    response = client.post("/api/settings", json={"api_key": fake, "free_confirmed": True})
    assert response.status_code == 200
    assert settings.runtime()["api_key"] == fake
    assert fake not in response.text + client.get("/api/status").text


def test_key_failures_are_specific_and_never_save_or_reflect_secret(setup):
    client, _, settings = setup
    fake = "AQ.SYNTHETIC_NOT_A_CREDENTIAL_123456789"
    response = client.post("/api/settings", json={"api_key": fake, "free_confirmed": False})
    assert response.status_code == 400 and "Free" in response.json()["detail"]
    assert fake not in response.text and not (settings.root / ".env").exists()
    for invalid in ("", "short", fake + "\nheader: injected", "x" * 4097):
        response = client.post("/api/settings", json={"api_key": invalid, "free_confirmed": True})
        assert response.status_code == 400
        if invalid:
            assert invalid not in response.text
    assert not (settings.root / ".env").exists()


def test_save_key_permission_failure_is_reported_without_key(setup, monkeypatch):
    client, _, _ = setup
    def denied(*args):
        raise PermissionError("private filesystem information")
    monkeypatch.setattr(Settings, "save_key", denied)
    fake = "AQ.SYNTHETIC_NOT_A_CREDENTIAL_123456789"
    response = client.post("/api/settings", json={"api_key": fake, "free_confirmed": True})
    assert response.status_code == 503 and "permisos" in response.json()["detail"]
    assert fake not in response.text and "private filesystem information" not in response.text


def test_invalid_citation_fails_closed(setup):
    _, store, _ = setup
    sources = store.retrieve("roaming")
    valid = {"status": "answered", "claims": [{"text": "El documento describe pruebas.", "source_id": "S1", "quote": sources[0]["text"][:100]}]}
    assert validate_answer(valid, sources)[0] == "answered"
    valid["claims"][0]["source_id"] = "S999"
    assert validate_answer(valid, sources) == ("unverified", [])
    valid["claims"][0].update(source_id="S1", quote="Una cita inventada que no existe en el documento.")
    assert validate_answer(valid, sources) == ("unverified", [])


def test_conflict_requires_two_documents_and_insufficient_discards_claims(setup):
    _, store, _ = setup
    sources = store.retrieve("pruebas inalámbrica", status="all")
    one = {"status": "conflict", "claims": [{"text": "Pruebas", "source_id": "S1", "quote": sources[0]["text"][:100]}]}
    assert validate_answer(one, sources) == ("unverified", [])
    assert validate_answer({"status": "insufficient", "claims": [{"text": "inventado"}]}, sources) == ("insufficient", [])


def test_cache_prevents_repeat_call_and_permission_change_invalidates(setup):
    _, store, settings = setup
    settings.save_key("TEST_ONLY_NOT_A_REAL_KEY_123456789", True)
    calls = []
    def provider(config, question, sources):
        calls.append(question)
        assert all(s["allow_cloud"] for s in sources)
        return {"status": "answered", "claims": [{"text": "Evidencia recuperada.", "source_id": "S1", "quote": sources[0]["text"][:100]}]}, {"totalTokenCount": 100}
    first = answer(store, settings, "pruebas roaming", "1", "current", "gemini", provider)
    second = answer(store, settings, "pruebas roaming", "1", "current", "gemini", provider)
    assert first["status"] == "answered" and second["cached"]
    assert len(calls) == store.usage() == 1
    for doc in store.documents():
        store.update(doc["id"], doc["status"], False)
    third = answer(store, settings, "pruebas roaming", "1", "current", "gemini", provider)
    assert third["status"] == "cloud_permission_required" and len(calls) == 1


def test_missing_key_and_paid_model_blocked_before_network(setup):
    _, store, settings = setup
    def forbidden(*_):
        pytest.fail("No debía llamarse al proveedor")
    with pytest.raises(ValueError, match="clave"):
        answer(store, settings, "roaming", "1", "current", "gemini", forbidden)
    settings.save_key("TEST_ONLY_NOT_A_REAL_KEY_123456789", True)
    (settings.root / ".env").write_text("GEMINI_API_KEY=TEST_ONLY_NOT_A_REAL_KEY_123456789\nGEMINI_MODEL=modelo-de-pago\nGEMINI_FREE_TIER_CONFIRMED=true", encoding="utf-8")
    with pytest.raises(ValueError, match="modelo"):
        answer(store, settings, "roaming", "1", "current", "gemini", forbidden)
    assert store.usage() == 0


def test_budget_reservation_is_atomic(setup):
    _, store, _ = setup
    def reserve(_):
        try:
            store.reserve_call(2, 0)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(reserve, range(6))) == 2
    assert store.usage() == 2


def test_gemini_request_contract_and_quota_failure(monkeypatch):
    original = httpx.Client
    def handler(request):
        body = json.loads(request.content)
        assert "systemInstruction" in body
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert request.headers["x-goog-api-key"] == "TEST_ONLY"
        assert "TEST_ONLY" not in str(request.url)
        return httpx.Response(429, json={"error": {"message": "Do not reflect provider payload"}})
    monkeypatch.setattr("app.qa.httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError, match="cuota"):
        call_gemini({"api_key": "TEST_ONLY", "model": "gemini-3.5-flash-lite"}, "Pregunta", [])


def test_docx_and_pdf_extraction_have_real_locations():
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Prueba de aceptación con evidencia documental suficiente.</w:t></w:r></w:p></w:body></w:document>')
    chunks, _ = extract("test.docx", stream.getvalue())
    assert chunks[0]["location"] == "Párrafo 1"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    pdf = BytesIO()
    writer.write(pdf)
    with pytest.raises(ValueError, match="OCR"):
        extract("scan.pdf", pdf.getvalue())


def test_invalid_documents_and_large_documents_are_rejected():
    with pytest.raises(ValueError):
        extract("corrupt.docx", b"bad zip")
    with pytest.raises(ValueError):
        extract("utf.txt", b"\xff\xfe")
    with pytest.raises(ValueError, match="10 MB"):
        extract("big.txt", b"a" * (MAX_BYTES + 1))


def test_upload_word_with_more_than_1000_paragraphs(setup):
    client, store, _ = setup
    paragraphs = [f"Requisito técnico de instalación y recepción número {index}." for index in range(1, 1201)]
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                         + ''.join(f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs)
                         + '</w:body></w:document>')
    response = client.post("/api/documents", files={"file": ("anexo-extenso.docx", stream.getvalue())},
                           data={"title": "Anexo extenso", "block": "4", "status": "current"})
    assert response.status_code == 200, response.text
    assert response.json()["created"] and response.json()["chunks"] < 100
    with store.connect() as db:
        chunks = db.execute("SELECT text,location FROM chunks WHERE document_id=? ORDER BY id", (response.json()["id"],)).fetchall()
    assert all(len(chunk["text"]) <= CHUNK_SIZE for chunk in chunks)
    combined = ' '.join(chunk["text"] for chunk in chunks)
    assert all(paragraph in combined for paragraph in paragraphs)
    assert chunks[0]["location"].startswith("Párrafos 1–")
    assert chunks[-1]["location"].endswith("–1200")
    assert store.usage() == 0


def test_grouping_keeps_page_and_paragraph_boundaries():
    units = [("Párrafo 3", "Primera evidencia."), ("Párrafos 5–6", "Segunda evidencia."),
             ("Página 1", "Texto de página uno."), ("Página 2", "Texto de página dos."),
             ("Párrafo 8", "Última evidencia.")]
    assert list(pack_paragraphs(units)) == [
        ("Párrafos 3–6", "Primera evidencia. Segunda evidencia."),
        ("Página 1", "Texto de página uno."), ("Página 2", "Texto de página dos."),
        ("Párrafo 8", "Última evidencia.")]


def test_oversized_paragraph_keeps_bounded_chunks_and_all_text():
    text = "evidencia técnica con trazabilidad " * 160
    chunks, _ = extract("largo.txt", text.encode())
    assert len(chunks) > 1 and all(len(chunk["text"]) <= CHUNK_SIZE for chunk in chunks)
    assert all(chunk["location"] == "Párrafo 1" for chunk in chunks)
    normalized = ' '.join(text.split())
    assert all(chunk["text"] in normalized for chunk in chunks)
    assert normalized.endswith(chunks[-1]["text"])


def test_evaluation_cases_are_reproducible(setup):
    from app.config import ROOT
    _, store, _ = setup
    cases = json.loads((ROOT / "evaluation/cases.json").read_text(encoding="utf-8"))
    for case in cases:
        sources = store.retrieve(case["question"], case["block"], case["status"])
        if case.get("expect_empty"):
            assert not sources
        if case.get("expected_file"):
            assert any(s["filename"] == case["expected_file"] and case["expected_text"] in s["text"] for s in sources), case["id"]
        if case.get("forbidden_file"):
            assert not any(s["filename"] == case["forbidden_file"] for s in sources)


def test_default_question_finds_new_drafts_without_treating_them_as_current(setup):
    client, store, _ = setup
    response = client.post('/api/documents', files={'file': ('pliego.txt', 'En el pliego de Campus Selva se solicitan siete equipos para la sede Bosque.'.encode())},
                           data={'title': 'Pliego Campus Selva'})
    response.raise_for_status()
    result = client.post('/api/ask', json={'question': '¿Cuántos equipos se solicitan para Bosque?'}).json()
    assert result['status'] == 'matches'
    assert any(s['document_id'] == response.json()['id'] and s['status'] == 'draft' for s in result['sources'])
    assert 'borrador' in result['message'].lower()
    assert not any(s['status'] == 'historical' for s in store.retrieve('pruebas inalámbrica'))
    assert store.usage() == 0


def test_explicit_filter_explains_draft_exclusion_without_changing_metadata(setup):
    client, store, _ = setup
    response = client.post('/api/documents', files={'file': ('borrador.txt', b'La cantidad marcadora filtroexclusion corresponde a siete equipos.')}, data={'title': 'Draft only'})
    response.raise_for_status()
    result = client.post('/api/ask', json={'question': 'filtroexclusion', 'status': 'current'}).json()
    assert result['status'] == 'filtered' and result['stage'] == 'filters'
    assert not result['sources'] and result['api_called'] is False
    assert next(d for d in store.documents() if d['id'] == response.json()['id'])['status'] == 'draft'


def test_authorized_draft_reaches_provider_and_private_draft_does_not(setup):
    client, store, settings = setup
    response = client.post('/api/documents', files={'file': ('draft.txt', b'Campus Selva solicita siete equipos para Bosque. Clave entidadbosque.')},
                           data={'title': 'Pliego ficticio', 'allow_cloud': 'true'})
    response.raise_for_status()
    settings.save_key('SYNTHETIC_NOT_A_CREDENTIAL_123456789', True)
    def provider(config, question, sources):
        assert all(s['allow_cloud'] and s['status'] == 'draft' for s in sources)
        return {'status': 'answered', 'claims': [{'text': 'El borrador solicita siete equipos para Bosque.',
                'source_id': 'S1', 'quote': 'Campus Selva solicita siete equipos para Bosque.'}]}, {}
    result = answer(store, settings, 'entidadbosque', 'all', 'active', 'gemini', provider)
    assert result['status'] == 'answered' and result['api_called']
    assert 'borrador' in result['message'].lower()
    store.update(response.json()['id'], 'draft', False)
    result = answer(store, settings, 'entidadbosque', 'all', 'active', 'gemini', lambda *_: pytest.fail('Private draft sent'))
    assert result['status'] == 'cloud_permission_required' and not result['api_called']


def test_partial_context_still_requires_a_real_literal_citation(setup):
    _, store, _ = setup
    sources = store.retrieve('roaming')
    payload = {'status': 'partial', 'claims': [{'text': 'Contexto relacionado con la consulta.', 'source_id': 'S1', 'quote': sources[0]['text'][:100]}]}
    assert validate_answer(payload, sources)[0] == 'partial'
    payload['claims'][0]['quote'] = 'Una cita falsa no presente en ninguna fuente.'
    assert validate_answer(payload, sources) == ('unverified', [])


def test_empty_library_and_no_word_matches_are_distinct(tmp_path):
    settings = Settings(root=tmp_path)
    store = Store(settings.db)
    result = answer(store, settings, 'equipos', 'all', 'active', 'local')
    assert result['status'] == 'empty_library' and not result['api_called']
    assert result['stage'] == 'library'
    client = TestClient(create_app(settings))
    client.post('/api/demo').raise_for_status()
    result = answer(store, settings, 'ZXQJ998877', 'all', 'active', 'local')
    assert result['status'] == 'insufficient' and result['stage'] == 'retrieval'
    assert not result['api_called']


def test_default_draft_reaches_provider_and_cached_partial_keeps_warning(setup):
    client, store, settings = setup
    settings.save_key('SYNTHETIC_NOT_A_CREDENTIAL_123456789', True)
    text = 'La sede Bosque solicita siete equipos de red en este borrador de Campus Selva.'
    client.post('/api/documents', files={'file': ('draft.txt', text.encode())},
                data={'title': 'Campus Selva', 'allow_cloud': 'true'}).raise_for_status()
    calls = []
    def provider(config, question, sources):
        calls.append(question)
        source = next(s for s in sources if text in s['text'])
        return {'status': 'partial', 'claims': [{'text': 'El borrador aporta contexto de equipos.', 'source_id': source['source_id'], 'quote': text}]}, {}
    first = answer(store, settings, 'equipos Bosque', 'all', 'active', 'gemini', provider)
    cached = answer(store, settings, 'equipos Bosque', 'all', 'active', 'gemini', provider)
    assert first['status'] == cached['status'] == 'partial'
    assert first['api_called'] and not cached['api_called'] and cached['cached']
    assert 'borradores' in first['message'] and 'borradores' in cached['message']
    assert len(calls) == 1
