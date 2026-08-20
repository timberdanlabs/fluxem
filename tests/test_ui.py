"""
Unit and integration tests for WebUI Dashboard & Persistent Configuration Store.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from fluxem.ingestion.pipeline import IngestionPipeline
from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad
from fluxem.storage import AppConfigData, ConfigStore, config_store


@pytest.mark.asyncio
async def test_ui_page_render(async_client):
    """Verify that /ui renders HTML dashboard."""
    response = await async_client.get("/ui")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "FluxEM" in response.text
    assert "deferrable_loads" in response.text


@pytest.mark.asyncio
async def test_get_ui_config(async_client):
    """Verify /api/v1/ui/config endpoint."""
    response = await async_client.get("/api/v1/ui/config")
    assert response.status_code == 200
    data = response.json()
    assert "default_timestep_minutes" in data
    assert "deferrable_loads" in data
    assert "solar_drift_threshold_pct" in data


@pytest.mark.asyncio
async def test_save_ui_config(async_client, tmp_path):
    """Verify /api/v1/ui/config POST endpoint updates configuration."""
    test_store = ConfigStore(config_path=tmp_path / "test_config.json")

    payload = {
        "default_timestep_minutes": 15,
        "default_currency": "EUR",
        "mqtt_enabled": True,
        "mqtt_broker_host": "192.168.1.88",
        "mqtt_broker_port": 1883,
        "mqtt_topic_prefix": "fluxem_home",
        "battery": {
            "soc_percent": 60.0,
            "capacity_kwh": 10.0,
            "max_charge_power_w": 4000.0,
            "max_discharge_power_w": 4000.0,
            "min_soc_percent": 15.0,
            "max_soc_percent": 95.0,
        },
        "deferrable_loads": [
            {
                "id": "heat_pump",
                "name": "Heat Pump",
                "nominal_power_w": 2800.0,
                "required_hours": 3.5,
                "continuous": True,
            }
        ],
        "enable_export_arbitrage": True,
        "min_arbitrage_profit_per_kwh": 0.04,
        "solar_drift_threshold_pct": 20.0,
    }

    response = await async_client.post("/api/v1/ui/config", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["config"]["default_timestep_minutes"] == 15
    assert res_data["config"]["enable_export_arbitrage"] is True
    assert len(res_data["config"]["deferrable_loads"]) == 1


@pytest.mark.asyncio
async def test_simulate_endpoint(async_client):
    """Verify /api/v1/ui/simulate endpoint runs optimization."""
    response = await async_client.post("/api/v1/ui/simulate")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "optimized"
    assert len(data["timestamps"]) == 24
    assert len(data["solar_forecast_w"]) == 24


def test_ingestion_merges_stored_webui_defaults(tmp_path):
    """
    Verify that when incoming Home Assistant payload omits battery specs
    and deferrable load definitions, IngestionPipeline automatically merges
    the configured WebUI defaults from ConfigStore.
    """
    # Configure defaults in store
    config_store.config.battery = BatteryState(
        soc_percent=50.0,
        capacity_kwh=13.5,
        min_soc_percent=10.0,
        max_soc_percent=100.0,
    )
    config_store.config.deferrable_loads = [
        DeferrableLoad(
            id="water_heater",
            name="Heat Pump Hot Water",
            nominal_power_w=3700.0,
            required_hours=3.0,
            continuous=True,
        )
    ]

    # Minimal payload from Home Assistant (only time-series + live sensors)
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    minimal_payload = {
        "timestamps": timestamps,
        "buy_prices": [0.20, 0.20, 0.20, 0.20],
        "solar_forecast": [0.0, 1000.0, 2000.0, 1000.0],
        "load_forecast": [500.0, 500.0, 500.0, 500.0],
        "battery_soc": 75.0,  # Just sensor state
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(minimal_payload)

    # Battery specs merged from WebUI, with SOC updated to 75%
    assert context.battery is not None
    assert context.battery.capacity_kwh == 13.5
    assert context.battery.soc_percent == 75.0

    # Deferrable loads merged from WebUI
    assert len(context.deferrable_loads) == 1
    assert context.deferrable_loads[0].id == "water_heater"
    assert context.deferrable_loads[0].nominal_power_w == 3700.0
