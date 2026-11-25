import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingest import CHUNK_SIZE, extract
from app.main import create_app


@pytest.mark.parametrize('filename,raw', [
    ('catalogo.csv', 'Producto,Unidades,Precio\nMonitor,7,150\nTeclado,3,25\n'),
    ('catalogo.csv', 'Producto;Unidades;Precio\nMonitor;7;150\nTeclado;3;25\n'),
    ('catalogo.tsv', 'Producto\tUnidades\tPrecio\nMonitor\t7\t150\nTeclado\t3\t25\n'),
])
def test_delimited_tables_keep_headers_values_and_logical_row(filename, raw):
    chunks, warnings = extract(filename, raw.encode('utf-8'))
    assert len(chunks) == 2 and all(c['kind'] == 'table' for c in chunks)
    assert chunks[0]['location'] == 'Registro · fila 2'
    assert 'Producto: Monitor | Unidades: 7 | Precio: 150' in chunks[0]['text']
    assert all(c['page'] is None for c in chunks)
    assert any('primera fila' in w for w in warnings)


def test_csv_quoted_newlines_empty_and_duplicate_headers_preserve_all_values():
    raw = '\ufeffNombre,Detalle,Detalle,,\nAurora,"Primera línea\nsegunda línea",adicional,valor,extra\n'
    chunks, _ = extract('ejemplo.csv', raw.encode('utf-8'))
    assert len(chunks) == 1
    text = chunks[0]['text']
    assert 'Detalle (columna 2): Primera línea segunda línea' in text
    assert 'Detalle (columna 3): adicional' in text
    assert 'Columna 4: valor' in text and 'Columna 5: extra' in text
    assert chunks[0]['location'] == 'Registro · fila 2'


def test_csv_long_cell_repeats_record_identity_and_label():
    raw = 'ID,Notas\nCASO-17,' + ('Evidencia disponible para revisión. ' * 150)
    chunks, _ = extract('registro.csv', raw.encode())
    assert len(chunks) > 1
    assert all(len(c['text']) <= CHUNK_SIZE for c in chunks)
    notes = [c for c in chunks if 'Notas: ' in c['text']]
    assert notes and all('ID: CASO-17' in c['text'] for c in notes)


def test_html_sections_tables_entities_and_inert_content():
    raw = '''<html><head><style>ignorestyle</style></head><body>
    <h1>Manual del producto</h1><h2>Instalación</h2>
    <p>Conecta el equipo &amp; revisa <b>la conexión</b>.</p>
    <script>ignoresecret()</script><iframe src="https://example.invalid/private">ignoreframe</iframe>
    <table><tr><th>Equipo</th><th>Cantidad</th></tr>
    <tr><td>Monitor</td><td>7</td></tr></table></body></html>'''
    chunks, warnings = extract('manual.html', raw.encode('utf-8'))
    combined = ' '.join(c['text'] for c in chunks)
    assert 'Conecta el equipo & revisa la conexión.' in combined
    assert 'ignorestyle' not in combined and 'ignoresecret' not in combined and 'ignoreframe' not in combined
    row = next(c for c in chunks if c['kind'] == 'table')
    assert row['text'] == 'Equipo: Monitor | Cantidad: 7'
    assert row['section'] == 'Manual del producto > Instalación'
    assert row['location'] == 'Tabla HTML 1 · fila 2'
    assert any('no se ejecutan scripts' in w for w in warnings)


def test_html_rowspan_retains_which_item_owns_the_values():
    raw = '''<h1>Inventario de prueba</h1><table>
    <tr><th>Sede</th><th>Equipo</th><th>Cantidad</th></tr>
    <tr><td rowspan="2">Roble</td><td>AP</td><td>7</td></tr>
    <tr><td>Switch</td><td>2</td></tr></table>'''
    chunks, _ = extract('inventario.htm', raw.encode())
    rows = [c for c in chunks if c['kind'] == 'table']
    assert len(rows) == 2
    assert 'Sede: Roble | Equipo: Switch | Cantidad: 2' in rows[1]['text']


def test_non_utf8_delimited_file_has_actionable_error():
    with pytest.raises(ValueError, match='UTF-8'):
        extract('registro.csv', b'Nombre,Notas\nAurora,informaci\xf3n\n')


def test_new_formats_are_searchable_locally_without_cloud_permission(tmp_path):
    client = TestClient(create_app(Settings(root=tmp_path), converter=None))
    response = client.post('/api/documents', files={'file': ('inventario.csv', b'Producto,Unidades\nMonitor,7\n')}, data={'title': 'Inventario ficticio'})
    response.raise_for_status()
    result = client.post('/api/ask', json={'question': 'Monitor unidades', 'mode': 'local'}).json()
    assert not result['api_called'] and result['sources']
    assert result['sources'][0]['kind'] == 'table'
    assert 'Unidades: 7' in result['sources'][0]['text']
    cloud = client.post('/api/ask', json={'question': 'Monitor unidades', 'mode': 'gemini'}).json()
    assert cloud['status'] == 'cloud_permission_required' and not cloud['api_called']
