"""
Integration tests for FluxEM FastAPI endpoints.
"""

import pytest


@pytest.mark.asyncio
async def test_health_check_endpoint(async_client):
    """Test /health endpoint."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "uptime_seconds" in data


@pytest.mark.asyncio
async def test_root_endpoint(async_client):
    """Test / endpoint."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "FluxEM"
    assert data["status"] == "online"


@pytest.mark.asyncio
async def test_config_endpoint(async_client):
    """Test /api/v1/config endpoint."""
    response = await async_client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert data["default_timestep_minutes"] == 30
    assert "drift_thresholds" in data


@pytest.mark.asyncio
async def test_ingest_endpoint(async_client, sample_payload_dict):
    """Test /api/v1/ingest endpoint with valid payload."""
    response = await async_client.post("/api/v1/ingest", json=sample_payload_dict)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("success", "warning")
    assert data["total_steps"] == 24
    assert data["timestep_minutes"] == 30
    assert data["forecast_summary"]["total_solar_kwh"] > 0


@pytest.mark.asyncio
async def test_optimize_endpoint(async_client, sample_payload_dict):
    """Test /api/v1/optimize endpoint with valid payload."""
    # Force reoptimize to guarantee full sweep
    payload = dict(sample_payload_dict)
    payload["force_reoptimize"] = True

    response = await async_client.post("/api/v1/optimize", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "optimized"
    assert len(data["timestamps"]) == 24
    assert "water_heater" in data["deferrable_load_power_w"]
    assert "pool_pump" in data["deferrable_load_power_w"]
    assert sum(data["deferrable_load_power_w"]["water_heater"]) > 0


@pytest.mark.asyncio
async def test_webhook_endpoint(async_client, sample_payload_dict):
    """Test /api/v1/webhook endpoint."""
    response = await async_client.post("/api/v1/webhook", json=sample_payload_dict)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("optimized", "held_by_watchdog")
    assert len(data["timestamps"]) == 24


@pytest.mark.asyncio
async def test_invalid_payload_error_handling(async_client):
    """Test error response when missing required fields."""
    response = await async_client.post("/api/v1/ingest", json={})
    assert response.status_code == 422
