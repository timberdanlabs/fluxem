"""
Test configuration and shared fixtures for FluxEM.
"""

import json
from pathlib import Path
from typing import Any, Dict
import pytest
from httpx import ASGITransport, AsyncClient

from fluxem.main import app, drift_watchdog
from fluxem.storage import AppConfigData, config_store


@pytest.fixture(autouse=True)
def reset_global_state():
    """Resets global in-memory state and config store before every test for clean isolation."""
    config_store._config = AppConfigData()
    drift_watchdog.clear_cache()
    yield
    config_store._config = AppConfigData()
    drift_watchdog.clear_cache()


@pytest.fixture
def sample_payload_dict() -> Dict[str, Any]:
    """Load the standard test payload dictionary."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_payload.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
async def async_client():
    """Async test client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
