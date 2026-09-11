async def test_health_ok(client):
    """Liveness touches nothing: it must answer even when every dependency is down."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
