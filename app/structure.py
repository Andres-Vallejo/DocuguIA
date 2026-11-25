"""Local structural extraction. Table values retain their column labels."""
from io import BytesIO, StringIO
import csv
from html.parser import HTMLParser
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import NamedTuple
from zipfile import ZipFile, BadZipFile

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


class Unit(NamedTuple):
    location: str
    text: str
    section: str = ""
    page: int | None = None
    kind: str = "text"


def clean(text):
    return " ".join(text.split())


def compact(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if c.isalnum())


def heading_level(text):
    text = clean(text)
    if not 4 <= len(text) <= 150 or len(text.split()) > 20:
        return None
    markdown = re.match(r'^(#{1,6})\s+\S', text)
    if markdown:
        return len(markdown[1])
    numbered = re.match(r'^(\d+(?:\.\d+)*)(?:\.|\))\s+\D', text)
    if not numbered:
        numbered = re.match(r'^(\d+\.\d+(?:\.\d+)*)\s+\D', text)
    if numbered and not text.endswith(('.', ':', ';')):
        return numbered[1].count('.') + 1
    letters = ''.join(c for c in text if c.isalpha())
    if len(letters) >= 6 and letters.isupper() and not text.endswith(('.', ';')):
        return 1
    return None


def advance_section(stack, text, level):
    title = re.sub(r'^#{1,6}\s+', '', clean(text))
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, title))
    return ' > '.join(t for _, t in stack)


def _decode_text(content):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Guarda el archivo de texto con codificación UTF-8.') from None
    if '\x00' in text:
        raise ValueError('El archivo no parece texto válido.')
    return text


def _labeled_rows(rows, section='', table_name='Tabla', header=True):
    if not rows:
        return []
    width = max(len(row) for row in rows)
    names = [clean(value) for value in rows[0]] if header else []
    names += [''] * (width - len(names))
    labels = [f'{name} (columna {i + 1})' if name and names.count(name) > 1
              else name or f'Columna {i + 1}' for i, name in enumerate(names)]
    units = []
    for index, row in enumerate(rows[1:] if header else rows, 2 if header else 1):
        fields = [(labels[col], clean(value)) for col, value in enumerate(row) if clean(value)]
        if not fields:
            continue
        location = f'{table_name} · fila {index}'
        text = ' | '.join(f'{key}: {value}' for key, value in fields)
        if len(text) <= 1400:
            units.append(Unit(location, text, section, None, 'table'))
            continue
        # Long rows repeat short identifiers and the cell label in every part.
        context = ' | '.join(f'{key}: {value}' for key, value in fields[:2] if len(key) + len(value) < 180)
        context = (context + ' | ') if context else ''
        for key, value in fields:
            prefix = context + key[:200] + ': '
            capacity, start = max(100, 1400 - len(prefix)), 0
            while start < len(value):
                end = min(len(value), start + capacity)
                if end < len(value):
                    boundary = value.rfind(' ', start + capacity // 2, end)
                    if boundary > start:
                        end = boundary
                units.append(Unit(location, prefix + value[start:end], section, None, 'table'))
                start = end
                while start < len(value) and value[start].isspace():
                    start += 1
    return units


def delimited_units(content, delimiter=None):
    text = _decode_text(content)
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=',;\t').delimiter
        except csv.Error:
            delimiter = ','
    try:
        rows = list(csv.reader(StringIO(text, newline=''), delimiter=delimiter, strict=True))
    except csv.Error:
        raise ValueError('No se pudo leer la tabla. Revisa los separadores, las comillas y el tamaño de las celdas.') from None
    rows = [row for row in rows if any(clean(value) for value in row)]
    return _labeled_rows(rows, 'Datos tabulares', 'Registro'), [
        'CSV/TSV: la primera fila se interpreta como encabezados; la ubicación indica el registro lógico, no la línea física.']


class _HTMLDocument(HTMLParser):
    """Parse uploaded markup as inert text, without URLs, scripts or rendering."""
    blocks = {'p', 'div', 'li', 'blockquote', 'pre', 'section', 'article', 'br', 'hr'}
    excluded = {'script', 'style', 'head', 'noscript', 'template', 'iframe', 'object', 'svg'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.units, self.stack, self.pending, self.skipped = [], [], [], []
        self.section, self.heading, self.paragraph = '', None, 0
        self.depth, self.rows, self.row, self.cell = 0, [], None, None
        self.table_number, self.headers = 0, False
        self.rowspans, self.column = {}, 0

    def flush(self):
        text = clean(''.join(self.pending))
        self.pending = []
        if text:
            if self.heading:
                self.section = advance_section(self.stack, text, self.heading)
            self.paragraph += 1
            self.units.append(Unit(f'Bloque HTML {self.paragraph}', text, self.section))

    def handle_starttag(self, tag, attrs):
        if self.skipped:
            if tag in self.excluded:
                self.skipped.append(tag)
            return
        if tag in self.excluded:
            self.skipped.append(tag)
            return
        if tag == 'table':
            self.flush()
            self.depth += 1
            if self.depth == 1:
                self.rows, self.rowspans, self.headers = [], {}, False
                self.table_number += 1
            return
        if self.depth:
            if self.depth != 1:
                return
            if tag == 'tr':
                self.row, self.column = [], 0
            elif tag in {'td', 'th'} and self.row is not None:
                self.cell = []
                options = dict(attrs)
                def span(name):
                    try:
                        return min(100, max(1, int(options.get(name, '1'))))
                    except (ValueError, TypeError):
                        return 1
                self.colspan, self.rowspan = span('colspan'), span('rowspan')
                if tag == 'th' and not self.rows:
                    self.headers = True
            elif self.cell is not None and tag in self.blocks:
                self.cell.append(' ')
            return
        if re.fullmatch(r'h[1-6]', tag):
            self.flush()
            self.heading = int(tag[1])
        elif tag in self.blocks:
            self.flush()

    def handle_endtag(self, tag):
        if self.skipped:
            if tag == self.skipped[-1]:
                self.skipped.pop()
            return
        if tag == 'table' and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.units.extend(_labeled_rows(self.rows, self.section, f'Tabla HTML {self.table_number}', self.headers))
            return
        if self.depth:
            if self.depth != 1:
                return
            if tag in {'td', 'th'} and self.cell is not None and self.row is not None:
                self._carry_spans()
                value = clean(''.join(self.cell))
                for _ in range(self.colspan):
                    self.row.append(value)
                    if self.rowspan > 1:
                        self.rowspans[self.column] = [value, self.rowspan - 1]
                    self.column += 1
                self.cell = None
            elif tag == 'tr' and self.row is not None:
                self._carry_spans()
                self.rows.append(self.row)
                self.row, self.cell = None, None
            return
        if re.fullmatch(r'h[1-6]', tag):
            self.flush()
            self.heading = None
        elif tag in self.blocks:
            self.flush()

    def _carry_spans(self):
        while self.column in self.rowspans:
            value, remaining = self.rowspans[self.column]
            self.row.append(value)
            if remaining <= 1:
                del self.rowspans[self.column]
            else:
                self.rowspans[self.column][1] -= 1
            self.column += 1

    def handle_data(self, value):
        if self.skipped:
            return
        if self.depth:
            if self.cell is not None:
                self.cell.append(value)
        else:
            self.pending.append(value)


def html_units(content):
    parser = _HTMLDocument()
    parser.feed(_decode_text(content))
    parser.close()
    parser.flush()
    return parser.units, ['HTML: se consulta el texto del archivo cargado; no se ejecutan scripts ni se descargan enlaces. Las tablas anidadas o encabezados complejos requieren revisión.']


def _text(element):
    paragraphs = [element] if element.tag == W + 'p' else element.findall('.//w:p', NS)
    return clean(' '.join(''.join(t.text or '' for t in p.findall('.//w:t', NS)) for p in paragraphs))


def _body_blocks(element):
    for child in element:
        if child.tag in {W + 'p', W + 'tbl'}:
            yield child
        elif child.tag != W + 'sectPr':
            yield from _body_blocks(child)


def _table_rows(table):
    rows, vertical = [], {}
    for row in table.findall('./w:tr', NS):
        before = row.find('./w:trPr/w:gridBefore', NS)
        offset = min(100, max(0, int(before.get(W + 'val', '0')))) if before is not None else 0
        values = [''] * offset
        for cell in row.findall('./w:tc', NS):
            column = len(values)
            span = cell.find('./w:tcPr/w:gridSpan', NS)
            width = min(100, max(1, int(span.get(W + 'val', '1')))) if span is not None else 1
            value = _text(cell)
            merge = cell.find('./w:tcPr/w:vMerge', NS)
            if merge is not None and merge.get(W + 'val', 'continue') != 'restart' and not value:
                value = vertical.get(column, '')
            for offset in range(width):
                if merge is not None:
                    vertical[column + offset] = value
                else:
                    vertical.pop(column + offset, None)
            values.extend([value] * width)
        header_flag = row.find('./w:trPr/w:tblHeader', NS)
        explicit_header = header_flag is not None and header_flag.get(W + 'val', 'true') not in {'0', 'false', 'off'}
        rows.append((values, explicit_header))
    return rows


def docx_units(content):
    try:
        with ZipFile(BytesIO(content)) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 20 * 1024 * 1024:
                raise ValueError('El contenido descomprimido del DOCX es demasiado grande.')
            xml = archive.read(info)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                raise ValueError('El DOCX contiene XML no permitido.')
            tree = ET.fromstring(xml)
            style_levels = {}
            if 'word/styles.xml' in archive.namelist():
                styles = ET.fromstring(archive.read('word/styles.xml'))
                for style in styles.findall('./w:style', NS):
                    outline = style.find('./w:pPr/w:outlineLvl', NS)
                    if outline is not None:
                        style_levels[style.get(W + 'styleId')] = min(9, int(outline.get(W + 'val', '0')) + 1)
            body = tree.find('./w:body', NS)
            if body is None:
                raise ValueError('El archivo DOCX no contiene un cuerpo de documento.')
            numbers = {paragraph: i for i, paragraph in enumerate(tree.findall('.//w:p', NS), 1)}
            units, stack, hints = [], [], {}
            section, previous, table_number = '', '', 0
            for block in _body_blocks(body):
                if block.tag == W + 'p':
                    text = _text(block)
                    if not text:
                        continue
                    outline = block.find('./w:pPr/w:outlineLvl', NS)
                    style = block.find('./w:pPr/w:pStyle', NS)
                    style_id = style.get(W + 'val', '') if style is not None else ''
                    level = style_levels.get(style_id)
                    if outline is not None:
                        level = int(outline.get(W + 'val', '0')) + 1
                    if level is None:
                        style_match = re.search(r'(?:heading|titulo|título)\s*([1-9])', style_id, re.I)
                        level = int(style_match[1]) if style_match else heading_level(text)
                    if level is not None and len(text) <= 180:
                        section = advance_section(stack, text, level)
                        hints[compact(text)] = level
                    units.append(Unit(f'Párrafo {numbers[block]}', text, section))
                    previous = text
                    continue
                table_number += 1
                rows = _table_rows(block)
                if not rows:
                    continue
                columns = max(len(values) for values, _ in rows)
                header_count = 0
                for _, flag in rows:
                    if not flag:
                        break
                    header_count += 1
                if not header_count:
                    first = rows[0][0]
                    # Unmarked numeric/data rows are retained, never consumed as headers.
                    if len(set(first)) >= 2 and all(value and len(value) <= 100 and not re.fullmatch(r'[\d\s.,%+-]+', value) for value in first):
                        header_count = 1
                headers = []
                for col in range(columns):
                    parts = list(dict.fromkeys(values[col] for values, _ in rows[:header_count] if col < len(values) and values[col]))
                    headers.append(' / '.join(parts) or f'Columna {col + 1}')
                caption = previous if re.match(r'^tabla\b', previous, re.I) and len(previous) <= 220 else f'Tabla {table_number}'
                for row_index, (values, _) in enumerate(rows[header_count:], header_count + 1):
                    fields = [f'{headers[col]}: {value}' for col, value in enumerate(values) if value]
                    if fields:
                        location = f'Tabla {table_number} · fila {row_index}'
                        units.append(Unit(location, caption + '\n' + ' | '.join(fields), section, None, 'table'))
            return units, hints
    except (BadZipFile, KeyError, ET.ParseError, OverflowError):
        raise ValueError('El archivo DOCX no es válido.') from None


def pdf_units(content, hints=None):
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ValueError('Exporta una copia del PDF sin contraseña.')
        if len(reader.pages) > 200:
            raise ValueError('Máximo 200 páginas por PDF en esta versión.')
        units, warnings, pages, stack, section = [], [], [], [], ''
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ''
            pages.append(text)
            if not text.strip():
                warnings.append(f'Página {number} sin texto extraíble; necesita OCR.')
                continue
            pending = []
            for line in text.splitlines():
                line = clean(line)
                if not line:
                    continue
                level = (hints or {}).get(compact(line)) or heading_level(line)
                if level is not None:
                    if pending:
                        units.append(Unit(f'Página {number}', ' '.join(pending), section, number))
                    pending = []
                    section = advance_section(stack, line, level)
                pending.append(line)
            if pending:
                units.append(Unit(f'Página {number}', ' '.join(pending), section, number))
        # Bordered PDF tables are represented as labeled rows as well as text.
        try:
            import pdfplumber
            table_number = 0
            with pdfplumber.open(BytesIO(content)) as pdf:
                for page in pdf.pages:
                    for table in page.find_tables():
                        rows = [[clean(cell or '') for cell in row] for row in table.extract()]
                        if len(rows) < 2 or len(rows[0]) < 2:
                            continue
                        table_number += 1
                        first = rows[0]
                        has_header = all(value and not re.fullmatch(r'[\d\s.,%+-]+', value) for value in first)
                        headers = first if has_header else [f'Columna {i + 1}' for i in range(len(first))]
                        above = page.crop((0, 0, page.width, max(1, table.bbox[1]))).extract_text() or ''
                        table_section = ''
                        for line in above.splitlines():
                            if heading_level(line) is not None:
                                table_section = clean(line)
                        for index, values in enumerate(rows[1:] if has_header else rows, 2 if has_header else 1):
                            fields = [f'{headers[col] if col < len(headers) else "Columna " + str(col + 1)}: {value}'
                                      for col, value in enumerate(values) if value]
                            if fields:
                                units.append(Unit(f'Página {page.page_number} · tabla {table_number} · fila {index}',
                                                  ' | '.join(fields), table_section, page.page_number, 'table'))
            if table_number:
                warnings.append('Tablas PDF detectadas automáticamente: revisa los encabezados y las celdas en la página original.')
        except ImportError:
            warnings.append('No está disponible el extractor de tablas PDF; se conserva el texto de las páginas.')
        except Exception:
            warnings.append('No se pudieron estructurar algunas tablas PDF; se conserva el texto de las páginas.')
        return units, warnings, pages
    except ValueError:
        raise
    except Exception:
        raise ValueError('No se pudo leer el PDF. Comprueba el archivo.') from None
