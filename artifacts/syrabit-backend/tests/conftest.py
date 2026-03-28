import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/test_syrabit")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-for-testing-only")
os.environ.setdefault("ADMIN_JWT_SECRET", "test-admin-jwt-secret-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("FIREWORKS_API_KEY", "test-fireworks-key")
os.environ.setdefault("SARVAM_API_KEY", "test-sarvam-key")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
os.environ.setdefault("ADMIN_PASSWORDS", '{"admin@syrabit.ai":"testpass123"}')


@pytest.fixture
def mock_db():
    mock = MagicMock()
    mock.users = AsyncMock()
    mock.conversations = AsyncMock()
    mock.analytics = AsyncMock()
    mock.payments = AsyncMock()
    mock.api_config = AsyncMock()
    mock.seo_topics = AsyncMock()
    return mock
