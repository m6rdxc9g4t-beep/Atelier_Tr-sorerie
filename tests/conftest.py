import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE_PATH": tmp_path / "test.db",
        "OLLAMA_URL": "http://127.0.0.1:9",  # port fermé : simule Ollama hors ligne
    })


class ApiClient:
    """Client de test qui ajoute l'en-tête anti-CSRF exigé par l'API."""

    def __init__(self, client):
        self.c = client
        self.h = {"X-Requested-With": "test"}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self.h, **kw)

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers=self.h)

    def delete(self, url):
        return self.c.delete(url, headers=self.h)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def api(client):
    return ApiClient(client)
