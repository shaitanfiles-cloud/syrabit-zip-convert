import pytest
from httpx import AsyncClient, ASGITransport
import asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_search_endpoint():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/search?q=physics")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))


@pytest.mark.asyncio
async def test_library_bundle():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/content/library-bundle")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "boards" in data


@pytest.mark.asyncio
async def test_seo_topics_requires_auth():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/seo/topics")
        assert resp.status_code in [200, 401]


@pytest.mark.asyncio
async def test_payment_no_auth():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/payments/create-order", json={"plan": "starter"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stripe_no_auth():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/payments/stripe/create-checkout", json={"plan": "starter"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_credit_topup_no_auth():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/payments/credit-topup", json={"credits": 100})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_security_headers():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert "x-content-type-options" in resp.headers
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "x-frame-options" in resp.headers


@pytest.mark.asyncio
async def test_error_response_shape():
    from server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/nonexistent-endpoint-xyz")
        assert resp.status_code in [404, 405]
        data = resp.json()
        assert "error" in data or "detail" in data
