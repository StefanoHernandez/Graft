async def test_health_ready(ready_client):
    resp = await ready_client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
