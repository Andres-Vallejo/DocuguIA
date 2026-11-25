"""Extraction and bounded paragraph chunks; no upload to any external service."""
from pathlib import Path
import re
from itertools import groupby

from .structure import Unit, advance_section, delimited_units, docx_units, heading_level, html_units, pdf_units

MAX_BYTES = 10 * 1024 * 1024
CHUNK_SIZE = 1500


def pack_paragraphs(units):
    """Group short adjacent paragraphs without losing their original locations.

    PDF pages stay separate. Long paragraphs are split by the existing bounded
    chunker below, so a large upload never makes the model context larger.
    """
    pending = []
    start = end = None
    length = 0

    def packed():
        location = f"Párrafo {start}" if start == end else f"Párrafos {start}–{end}"
        return location, " ".join(pending)

    for location, text in units:
        text = " ".join(text.split())
        match = re.fullmatch(r"Párrafos? (\d+)(?:–(\d+))?", location)
        if not match or len(text) > CHUNK_SIZE:
            if pending:
                yield packed()
                pending, length = [], 0
            yield location, text
            continue
        first, last = int(match[1]), int(match[2] or match[1])
        if pending and (length + 1 + len(text) > CHUNK_SIZE or first <= end):
            yield packed()
            pending, length = [], 0
        if not pending:
            start = first
        end = last
        length += len(text) + bool(pending)
        pending.append(text)
    if pending:
        yield packed()


def extract(filename: str, content: bytes):
    if not content or len(content) > MAX_BYTES:
        raise ValueError("El archivo debe tener contenido y ocupar como máximo 10 MB.")
    ext = Path(filename).suffix.lower()
    units, warnings, structured = [], [], None
    if ext in {".txt", ".md"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("Guarda el archivo de texto con codificación UTF-8.") from None
        if "\x00" in text:
            raise ValueError("El archivo no parece texto válido.")
        heading = ""
        heading_index = None
        for index, paragraph in enumerate(re.split(r"\n\s*\n", text), 1):
            paragraph = paragraph.strip()
            if ext == ".md" and re.fullmatch(r"#{1,6}[^\n]+", paragraph):
                heading = paragraph
                heading_index = index
                continue
            if paragraph:
                location = f"Párrafos {heading_index}–{index}" if heading else f"Párrafo {index}"
                units.append((location, (heading + "\n" + paragraph).strip()))
                heading = ""
                heading_index = None
    elif ext == ".pdf":
        try:
            structured, warnings, _ = pdf_units(content)
        except ValueError:
            raise
        except Exception:
            raise ValueError("No se pudo leer el PDF. Comprueba el archivo.") from None
    elif ext == ".docx":
        structured, _ = docx_units(content)
        warnings.append("DOCX: párrafos, secciones y filas de tablas extraídos; las páginas requieren la copia PDF local.")
    elif ext in {'.csv', '.tsv'}:
        structured, warnings = delimited_units(content, '\t' if ext == '.tsv' else None)
    elif ext in {'.html', '.htm'}:
        structured, warnings = html_units(content)
    else:
        raise ValueError("Formatos disponibles: PDF, DOCX, TXT, Markdown, CSV, TSV y HTML.")
    if structured is None:
        structured, stack, section = [], [], ''
        for location, text in units:
            first_line = text.splitlines()[0]
            level = heading_level(first_line)
            if level is not None:
                section = advance_section(stack, first_line, level)
            structured.append(Unit(location, text, section))
    if sum(len(unit.text) for unit in structured) > 1_000_000:
        raise ValueError("El documento supera el millón de caracteres extraídos.")
    chunks = []
    annotated = []
    for (section, page, kind), group in groupby(structured, key=lambda u: (u.section, u.page, u.kind)):
        group = list(group)
        packed = pack_paragraphs([(u.location, u.text) for u in group]) if kind == 'text' else [(u.location, u.text) for u in group]
        annotated.extend((location, text, section, page, kind) for location, text in packed)
    for location, text, section, page, kind in annotated:
        # Whitespace normalization preserves exact quotations for validation.
        text = " ".join(text.split())
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start + 1000, end)
                if boundary != -1:
                    end = boundary
            part = text[start:end].strip()
            if len(part) >= 15:
                chunks.append({"location": location, "text": part, "section": section, "page": page, "page_end": page, "kind": kind})
            if end == len(text):
                break
            start = max(end - 180, start + 1)
    if not chunks:
        raise ValueError("No se encontró texto suficiente. Los PDF escaneados necesitan OCR previo.")
    return chunks, warnings
