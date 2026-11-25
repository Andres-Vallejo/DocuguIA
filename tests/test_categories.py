"""Categories work across document topics without sending anything to a provider."""
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(root=tmp_path), converter=None))


def upload(client, category, title="Documento", text="Marcador compartido para comprobar la categoría del documento."):
    return client.post('/api/documents', files={'file': (title + '.txt', text.encode())},
                       data={'title': title, 'block': category})


def test_arbitrary_categories_filter_other_topics_but_include_general(client):
    for category in ('Investigación', 'Recursos humanos', 'general'):
        upload(client, category, category).raise_for_status()
    result = client.post('/api/ask', json={'question': 'Marcador compartido', 'block': 'Investigación'}).json()
    assert {source['block'] for source in result['sources']} == {'Investigación', 'general'}
    assert not result['api_called']
    assert client.get('/api/status').json()['calls_today'] == 0
    data = client.get('/api/documents').json()
    assert set(data['categories']) == {'general', 'Investigación', 'Recursos humanos'}
    assert {doc['block'] for doc in data['documents']} == set(data['categories'])


def test_legacy_numeric_categories_and_all_filter_still_work(client):
    upload(client, '1', 'Legado').raise_for_status()
    upload(client, 'Literatura', 'Lecturas').raise_for_status()
    scoped = client.post('/api/ask', json={'question': 'Marcador compartido', 'block': '1'}).json()
    assert {source['block'] for source in scoped['sources']} == {'1'}
    all_topics = client.post('/api/ask', json={'question': 'Marcador compartido', 'block': 'all'}).json()
    assert {source['block'] for source in all_topics['sources']} == {'1', 'Literatura'}


@pytest.mark.parametrize('category', ['all', 'ALL', 'x' * 81, '\t', 'tema\nprivado'])
def test_invalid_upload_categories_are_rejected(client, category):
    assert upload(client, category).status_code == 400
    assert client.get('/api/documents').json()['documents'] == []


@pytest.mark.parametrize('category', ['', ' ', 'ALL', 'x' * 81, 'tema\nprivado'])
def test_invalid_query_categories_are_rejected(client, category):
    response = client.post('/api/ask', json={'question': 'Marcador compartido', 'block': category})
    assert response.status_code == 400


def test_category_length_limit_and_upload_whitespace_normalization(client):
    category = 'C' * 80
    upload(client, '  ' + category + '  ').raise_for_status()
    assert client.get('/api/documents').json()['documents'][0]['block'] == category
    result = client.post('/api/ask', json={'question': 'Marcador compartido', 'block': category}).json()
    assert len(result['sources']) == 1


def test_empty_library_exposes_general_category(client):
    assert client.get('/api/documents').json()['categories'] == ['general']
