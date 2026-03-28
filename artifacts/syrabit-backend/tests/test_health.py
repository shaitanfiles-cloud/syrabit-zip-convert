import pytest
from httpx import AsyncClient, ASGITransport
import asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_health_endpoint():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert "dependencies" in data


@pytest.mark.asyncio
async def test_readiness_endpoint():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/ready")
        assert resp.status_code in [200, 503]
        data = resp.json()
        assert "status" in data


@pytest.mark.asyncio
async def test_openapi_docs():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "paths" in data
        assert len(data["paths"]) > 100
