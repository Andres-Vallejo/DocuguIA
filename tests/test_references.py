from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pypdf import PdfWriter, PdfReader
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.config import Settings
from app.ingest import extract
from app.main import create_app
from app.rendering import locate_pages


def word(body):
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '</w:body></w:document>')
    return stream.getvalue()


def paragraph(text, style=None):
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>'


def cell(text, properties=''):
    return '<w:tc><w:tcPr>' + properties + '</w:tcPr>' + paragraph(text) + '</w:tc>'


def pdf(pages, table_page=None):
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    for index, lines in enumerate(pages, 1):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        instructions = []
        def text(x, y, value):
            value = value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            return f'BT /F1 11 Tf 1 0 0 1 {x} {y} Tm ({value}) Tj ET'
        for number, line in enumerate(lines):
            instructions.append(text(50, 760 - number * 18, line))
        if index == table_page:
            for x in (50, 180, 320, 420):
                instructions.append(f'{x} 700 m {x} 610 l S')
            for y in (700, 670, 640, 610):
                instructions.append(f'50 {y} m 420 {y} l S')
            for row_index, row in enumerate([['Sede', 'Equipo', 'Cantidad'], ['Roble', 'AP', '7'], ['Pino', 'Switch', '3']]):
                for x, value in zip((58, 188, 328), row):
                    instructions.append(text(x, 681 - row_index * 30, value))
        content = DecodedStreamObject()
        content.set_data('\n'.join(instructions).encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_word_tables_keep_headers_quantities_sections_and_vertical_merges():
    body = paragraph('ESPECIFICACIONES', 'Heading1') + paragraph('4.1 Equipos por sede', 'Heading2')
    body += '<w:tbl><w:tr>' + ''.join(cell(t) for t in ['Sede', 'Equipo', 'Cantidad']) + '</w:tr>'
    body += '<w:tr>' + cell('Roble', '<w:vMerge w:val="restart"/>') + cell('AP') + cell('7') + '</w:tr>'
    body += '<w:tr>' + cell('', '<w:vMerge/>') + cell('Switch') + cell('2') + '</w:tr></w:tbl>'
    chunks, _ = extract('suministro.docx', word(body))
    tables = [c for c in chunks if c['kind'] == 'table']
    assert len(tables) == 2
    assert 'Sede: Roble' in tables[0]['text'] and 'Cantidad: 7' in tables[0]['text']
    assert 'Sede: Roble' in tables[1]['text'] and 'Cantidad: 2' in tables[1]['text']
    assert all(c['section'] == 'ESPECIFICACIONES > 4.1 Equipos por sede' for c in tables)
    assert tables[0]['location'] == 'Tabla 1 · fila 2'


def test_word_merged_multirow_headers_preserve_which_site_owns_each_count():
    body = paragraph('EQUIPOS') + '<w:tbl>'
    flag = '<w:trPr><w:tblHeader/></w:trPr>'
    body += '<w:tr>' + flag + cell('Roble', '<w:gridSpan w:val="2"/>') + cell('Pino', '<w:gridSpan w:val="2"/>') + '</w:tr>'
    body += '<w:tr>' + flag + ''.join(cell(t) for t in ['AP', 'Switch', 'AP', 'Switch']) + '</w:tr>'
    body += '<w:tr>' + ''.join(cell(t) for t in ['7', '2', '5', '3']) + '</w:tr></w:tbl>'
    chunks, _ = extract('sedes.docx', word(body))
    row = next(c for c in chunks if c['kind'] == 'table')
    assert 'Roble / AP: 7' in row['text'] and 'Pino / AP: 5' in row['text']


def test_word_omitted_leading_cells_keep_their_column_positions():
    body = '<w:tbl><w:tr>' + ''.join(cell(t) for t in ['Sede', 'AP', 'Switch']) + '</w:tr>'
    body += '<w:tr><w:trPr><w:gridBefore w:val="1"/></w:trPr>' + cell('7') + cell('2') + '</w:tr></w:tbl>'
    chunks, _ = extract('sedes.docx', word(body))
    row = next(c for c in chunks if c['kind'] == 'table')
    assert 'AP: 7' in row['text'] and 'Switch: 2' in row['text']
    assert 'Sede: 7' not in row['text']


def test_pdf_tables_have_original_page_and_labeled_values():
    raw = pdf([['1. Introduccion', 'Documento ficticio de prueba.'], ['2. Equipos por sede']], table_page=2)
    chunks, _ = extract('sedes.pdf', raw)
    row = next(c for c in chunks if c['kind'] == 'table' and 'Roble' in c['text'])
    assert row['page'] == row['page_end'] == 2
    assert row['section'] == '2. Equipos por sede'
    assert 'Cantidad: 7' in row['text'] and 'Sede: Roble' in row['text']


def test_page_lookup_does_not_guess_for_ambiguous_repeated_text():
    phrase = 'El texto se repite literalmente en dos paginas.'
    assert locate_pages(phrase, [phrase, phrase]) == (None, None)
    assert locate_pages('La sede Roble solicita siete equipos.', ['Portada', 'La sede Roble solicita siete equipos.']) == (2, 2)
    assert locate_pages('Inicio de evidencia y final de evidencia.', ['Inicio de evidencia y', 'final de evidencia.']) == (1, 2)


def test_table_caption_does_not_guess_between_repeated_rows():
    caption = 'Tabla 1. Distribucion de equipos por sede'
    row = caption + '\nSede: Roble | Equipo: Punto de acceso | Cantidad: 7'
    pages = [caption, 'Roble Punto de acceso 7', 'Roble Punto de acceso 7']
    assert locate_pages(row, pages, 'table', row) == (None, None)


def test_upload_word_builds_local_pdf_link_without_cloud_calls(tmp_path):
    settings = Settings(root=tmp_path)
    text = 'La sede Roble solicita siete equipos de red.'
    reference = pdf([['PORTADA FICTICIA'], ['2. Equipos por sede', text]])
    app = create_app(settings, converter=lambda content, directory: reference)
    client = TestClient(app)
    raw = word(paragraph('2. Equipos por sede', 'Heading1') + paragraph(text))
    response = client.post('/api/documents', files={'file': ('pliego.docx', raw)}, data={'title': 'Pliego ficticio'})
    response.raise_for_status()
    result = client.post('/api/ask', json={'question': 'equipos Roble'}).json()
    source = next(s for s in result['sources'] if text in s['text'])
    assert source['page'] == 2 and source['page_origin'] == 'generated_pdf'
    assert source['section'] == '2. Equipos por sede'
    preview = client.get(source['preview_url'])
    assert preview.status_code == 200 and preview.headers['content-type'] == 'application/pdf'
    assert len(PdfReader(BytesIO(preview.content)).pages) == 2
    assert not result['api_called']
    client.delete('/api/documents/' + response.json()['id']).raise_for_status()
    assert client.get(source['preview_url']).status_code == 404


def test_native_pdf_preserves_its_page_without_word_conversion(tmp_path):
    client = TestClient(create_app(Settings(root=tmp_path), converter=lambda *_: (_ for _ in ()).throw(AssertionError('Unexpected converter'))))
    raw = pdf([['1. Equipos', 'La sede Roble solicita siete equipos de red.']])
    client.post('/api/documents', files={'file': ('original.pdf', raw)}, data={'title': 'Original PDF'}).raise_for_status()
    source = client.post('/api/ask', json={'question': 'equipos Roble'}).json()['sources'][0]
    assert source['page'] == 1 and source['page_origin'] == 'original_pdf'
