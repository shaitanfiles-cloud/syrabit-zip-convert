import pytest
from httpx import AsyncClient, ASGITransport
import asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_login_missing_fields():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/login", json={})
        assert resp.status_code in [400, 422]


@pytest.mark.asyncio
async def test_login_invalid_credentials():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/login", json={
            "email": "nonexistent@test.com",
            "password": "wrongpassword"
        })
        assert resp.status_code in [401, 404]


@pytest.mark.asyncio
async def test_protected_endpoint_no_token():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/usage/me")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_bad_token():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/usage/me", headers={
            "Authorization": "Bearer invalid-token-here"
        })
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_wrong_password():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/admin/login", json={
            "email": "admin@syrabit.ai",
            "password": "wrongpassword"
        })
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_endpoint_no_token():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/users")
        assert resp.status_code == 401
