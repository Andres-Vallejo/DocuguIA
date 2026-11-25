"""Local reference PDFs and conservative page lookup. No network/API calls."""
from bisect import bisect_right
from io import BytesIO
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .ingest import MAX_BYTES, extract
from .structure import compact, docx_units


def converter_path():
    candidates = [shutil.which('soffice'), shutil.which('libreoffice'),
                  r'C:\Program Files\LibreOffice\program\soffice.com',
                  r'C:\Program Files\LibreOffice\program\soffice.exe',
                  '/Applications/LibreOffice.app/Contents/MacOS/soffice']
    return next((str(p) for p in candidates if p and Path(p).is_file()), None)


def render_docx_pdf(content, data_dir):
    executable = converter_path()
    if not executable:
        return None
    scratch = Path(data_dir) / 'render-tmp'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, prefix='reference-', ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        source = root / 'reference.docx'
        # Only the temporary rendering copy is sanitized; original bytes are preserved.
        with ZipFile(BytesIO(content)) as original, ZipFile(source, 'w') as sanitized:
            for entry in original.infolist():
                if entry.file_size > 30 * 1024 * 1024:
                    return None
                raw = original.read(entry)
                if entry.filename.endswith('.rels'):
                    tree = ET.fromstring(raw)
                    removed = False
                    for rel in list(tree):
                        if rel.get('TargetMode') == 'External':
                            tree.remove(rel)
                            removed = True
                    if removed:
                        ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/relationships')
                        raw = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
                if 'vbaproject' not in entry.filename.lower():
                    sanitized.writestr(entry, raw)
        profile = root / 'profile'
        user = profile / 'user'
        user.mkdir(parents=True)
        (user / 'registrymodifications.xcu').write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>', encoding='utf-8')
        command = [executable, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo',
                   '--norestore', '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(root), str(source)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        environment = os.environ.copy()
        for variable in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
            environment.pop(variable, None)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags, env=environment)
        try:
            process.communicate(timeout=80)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                               creationflags=flags, timeout=10)
            process.kill()
            process.communicate()
            return None
        target = root / 'reference.pdf'
        return target.read_bytes() if process.returncode == 0 and target.is_file() else None


def locate_pages(text, pages, kind='text', raw_unit=None, *, normalized_pages=None):
    """Return a page/range only when exact text anchors locate it unambiguously."""
    normalized = normalized_pages if normalized_pages is not None else [compact(page) for page in pages]
    probe = compact(text)
    if kind == 'table' and raw_unit:
        fields = raw_unit.split('\n', 1)[-1].split(' | ')
        probe = ''.join(compact(field.split(': ', 1)[-1]) for field in fields)
    if len(probe) < 15:
        return None, None
    joined = ''.join(normalized)
    boundaries, position = [], 0
    for page in normalized:
        position += len(page)
        boundaries.append(position)
    first = joined.find(probe)
    if first >= 0 and joined.find(probe, first + 1) < 0:
        return bisect_right(boundaries, first) + 1, bisect_right(boundaries, first + len(probe) - 1) + 1
    if kind == 'table':
        # A repeated row may be disambiguated by an exact, unique table caption.
        candidates = [i for i, page in enumerate(normalized, 1) if probe in page]
        caption = compact(raw_unit.split('\n', 1)[0]) if raw_unit else ''
        caption_pages = [i for i, page in enumerate(normalized, 1) if len(caption) >= 20 and caption in page]
        if len(caption_pages) == 1:
            following = [i for i in candidates if i >= caption_pages[0]]
            if len(following) == 1:
                return following[0], following[0]
        return None, None
    # Page headers/footers can interrupt a paragraph; require two unique anchors.
    if len(probe) >= 120:
        start, end = probe[:70], probe[-70:]
        starts = [i for i, page in enumerate(normalized, 1) if page.count(start) == 1]
        ends = [i for i, page in enumerate(normalized, 1) if page.count(end) == 1]
        if len(starts) == len(ends) == 1 and 0 <= ends[0] - starts[0] <= 2:
            return starts[0], ends[0]
    return None, None


def prepare_document(filename, content, data_dir, converter=render_docx_pdf):
    chunks, warnings = extract(filename, content)
    ext = Path(filename).suffix.lower()
    if ext == '.pdf':
        return chunks, warnings, content
    if ext != '.docx':
        return chunks, warnings, None
    preview = None
    if converter is not None:
        try:
            preview = converter(content, data_dir)
        except (OSError, ValueError, ET.ParseError):
            preview = None
    if not preview:
        warnings.append('Página no disponible: no se pudo generar el PDF local. Se conservan sección, párrafos y tablas.')
        return chunks, warnings, None
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(preview))
    if len(reader.pages) > 200:
        warnings.append('El PDF local supera 200 páginas; se conservan referencias por párrafo y tabla.')
        return chunks, warnings, None
    pages = [page.extract_text() or '' for page in reader.pages]
    normalized_pages = [compact(page) for page in pages]
    numbered_headings = {}
    for page in pages:
        for line in page.splitlines():
            heading = re.match(r'^\s*(\d+(?:\.\d+)*\.?)\s+(.{4,150})\s*$', line)
            if heading:
                numbered_headings.setdefault(compact(heading[2]), set()).add(heading[1])
    raw_units, _ = docx_units(content)
    raw_by_location = {unit.location: unit.text for unit in raw_units}
    for chunk in chunks:
        chunk['page'], chunk['page_end'] = locate_pages(chunk['text'], pages, chunk['kind'], raw_by_location.get(chunk['location']), normalized_pages=normalized_pages)
        section_parts = []
        for part in chunk['section'].split(' > '):
            title = re.sub(r'^\d+(?:\.\d+)*[.)]?\s+', '', part)
            numbers = numbered_headings.get(compact(title), set())
            section_parts.append(next(iter(numbers)) + ' ' + title if len(numbers) == 1 else part)
        chunk['section'] = ' > '.join(section_parts)
    warnings = [w for w in warnings if not w.startswith('DOCX:')]
    warnings.append('Las páginas corresponden al PDF de referencia generado localmente; su distribución puede diferir de Word.')
    missing = sum(chunk['page'] is None for chunk in chunks)
    if missing:
        warnings.append(f'{missing} fragmentos sin página inequívoca; conservan la sección y la ubicación original.')
    return chunks, warnings, preview


def save_local_files(data_dir, docid, filename, content, preview):
    originals = Path(data_dir) / 'originals'
    originals.mkdir(parents=True, exist_ok=True)
    (originals / (docid + Path(filename).suffix.lower())).write_bytes(content)
    if preview:
        previews = Path(data_dir) / 'previews'
        previews.mkdir(parents=True, exist_ok=True)
        (previews / (docid + '.pdf')).write_bytes(preview)
