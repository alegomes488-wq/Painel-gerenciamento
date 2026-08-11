"""T-30: docs públicos no painel (default) — contraste com o site."""
def test_docs_publicos_no_painel(app_env, fake_db, client):
    assert client.get("/docs").status_code == 200
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "paths" in r.json()
