import os
from starlette.testclient import TestClient
from app.main import app

def test_docs_available():
    client = TestClient(app)
    resp = client.get(os.getenv('SSA_DOCS_URL', '/docs'))
    assert resp.status_code in (200, 307, 308)

