"""
Unit tests for Direct Home Assistant API Integration and Forecast Extraction.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from fluxem.integrations.homeassistant import HomeAssistantClient
from fluxem.models.loads import DeferrableLoad
from fluxem.storage import config_store


@pytest.mark.asyncio
async def test_ha_client_test_connection_success():
    """Verify HomeAssistantClient.test_connection with valid mock response."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="valid_token")

    mock_response = httpx.Response(
        status_code=200,
        json={"message": "API running.", "version": "2026.8.0", "location_name": "Home"},
        request=httpx.Request("GET", "http://ha.local:8123/api/"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        success, msg, info = await client.test_connection()
        assert success is True
        assert "Successfully connected" in msg
        assert info["version"] == "2026.8.0"


@pytest.mark.asyncio
async def test_ha_client_test_connection_auth_failed():
    """Verify HomeAssistantClient.test_connection with 401 Unauthorized."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="bad_token")

    mock_response = httpx.Response(
        status_code=401,
        text="401: Unauthorized",
        request=httpx.Request("GET", "http://ha.local:8123/api/"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        success, msg, _ = await client.test_connection()
        assert success is False
        assert "Invalid Long-Lived Access Token" in msg


@pytest.mark.asyncio
async def test_ha_client_fetch_entities():
    """Verify HomeAssistantClient.fetch_entities extracts and sorts domain entities."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="valid_token")

    mock_states = [
        {"entity_id": "sensor.solcast_pv_forecast", "state": "3.5", "attributes": {"friendly_name": "Solcast PV Forecast", "unit_of_measurement": "kW"}},
        {"entity_id": "switch.water_heater", "state": "on", "attributes": {"friendly_name": "Water Heater Switch"}},
        {"entity_id": "light.living_room", "state": "off", "attributes": {"friendly_name": "Living Room Light"}},
    ]

    mock_response = httpx.Response(
        status_code=200,
        json=mock_states,
        request=httpx.Request("GET", "http://ha.local:8123/api/states"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        entities = await client.fetch_entities(domain_filter=["sensor", "switch"])
        assert len(entities) == 2
        entity_ids = [e["entity_id"] for e in entities]
        assert "sensor.solcast_pv_forecast" in entity_ids
        assert "switch.water_heater" in entity_ids
        assert "light.living_room" not in entity_ids


@pytest.mark.asyncio
async def test_ha_client_fetch_entities_smart_categorization():
    """Verify HomeAssistantClient classifies solar, prices, battery, and excludes irrelevant sensors."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="valid_token")

    mock_states = [
        {
            "entity_id": "sensor.solcast_forecast_today",
            "state": "25.4",
            "attributes": {
                "friendly_name": "Solcast Forecast Today",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "detailedForecast": [{"period_start": "2026-08-20T00:00:00Z", "pv_estimate": 1.5}],
            },
        },
        {
            "entity_id": "sensor.amber_general_forecast",
            "state": "0.28",
            "attributes": {
                "friendly_name": "Amber General Price",
                "unit_of_measurement": "c/kWh",
                "device_class": "monetary",
                "forecasts": [{"start_time": "2026-08-20T00:00:00Z", "per_kwh": 0.28}],
            },
        },
        {
            "entity_id": "sensor.amber_feed_in_forecast",
            "state": "0.08",
            "attributes": {
                "friendly_name": "Amber Feed In Price",
                "unit_of_measurement": "c/kWh",
                "device_class": "monetary",
                "forecasts": [{"start_time": "2026-08-20T00:00:00Z", "per_kwh": 0.08}],
            },
        },
        {
            "entity_id": "sensor.powerwall_battery_soc",
            "state": "78",
            "attributes": {
                "friendly_name": "Tesla Powerwall SOC",
                "unit_of_measurement": "%",
                "device_class": "battery",
            },
        },
        {
            "entity_id": "sensor.printer_3d_nozzle_temp",
            "state": "210",
            "attributes": {
                "friendly_name": "3D Printer Nozzle Temperature",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
            },
        },
        {
            "entity_id": "sensor.printer_3d_power",
            "state": "150",
            "attributes": {
                "friendly_name": "3D Printer Power Consumption",
                "unit_of_measurement": "W",
                "device_class": "power",
            },
        },
    ]

    mock_response = httpx.Response(
        status_code=200,
        json=mock_states,
        request=httpx.Request("GET", "http://ha.local:8123/api/states"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        entities = await client.fetch_entities()

        by_id = {e["entity_id"]: e for e in entities}

        # Solcast -> categorized in 'solar' (and 'power')
        assert "solar" in by_id["sensor.solcast_forecast_today"]["categories"]
        assert by_id["sensor.solcast_forecast_today"]["has_forecast"] is True

        # Amber General -> categorized in 'buy_price'
        assert "buy_price" in by_id["sensor.amber_general_forecast"]["categories"]
        assert "solar" not in by_id["sensor.amber_general_forecast"]["categories"]

        # Amber Feed-in -> categorized in 'sell_price'
        assert "sell_price" in by_id["sensor.amber_feed_in_forecast"]["categories"]
        assert "buy_price" not in by_id["sensor.amber_feed_in_forecast"]["categories"]

        # Battery SOC -> categorized in 'battery'
        assert "battery" in by_id["sensor.powerwall_battery_soc"]["categories"]

        # 3D printer power -> categorized in 'power' (for appliance power meters), NOT in solar, buy_price, or battery
        assert "power" in by_id["sensor.printer_3d_power"]["categories"]
        assert "solar" not in by_id["sensor.printer_3d_power"]["categories"]
        assert "buy_price" not in by_id["sensor.printer_3d_power"]["categories"]
        assert "battery" not in by_id["sensor.printer_3d_power"]["categories"]

        # 3D printer temperature -> not in any energy category
        assert len(by_id["sensor.printer_3d_nozzle_temp"]["categories"]) == 0



@pytest.mark.asyncio
async def test_ha_client_extract_solcast_and_amber():
    """
    Verify that HomeAssistantClient correctly unpacks Solcast detailedForecast
    (converting kW to Watts) and Amber pricing forecasts.
    """
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="valid_token")

    # Solcast mock state with detailedForecast in kW
    solcast_state = {
        "entity_id": "sensor.solcast_pv_forecast",
        "state": "2.4",
        "attributes": {
            "detailedForecast": [
                {"period_start": "2026-08-20T00:00:00Z", "pv_estimate": 0.0},
                {"period_start": "2026-08-20T00:30:00Z", "pv_estimate": 1.5},
                {"period_start": "2026-08-20T01:00:00Z", "pv_estimate": 3.8},
                {"period_start": "2026-08-20T01:30:00Z", "pv_estimate": 4.2},
            ]
        },
    }

    # Amber mock state with forecasts in $/kWh
    amber_state = {
        "entity_id": "sensor.amber_general_forecast",
        "state": "0.25",
        "attributes": {
            "forecasts": [
                {"start_time": "2026-08-20T00:00:00Z", "per_kwh": 0.22},
                {"start_time": "2026-08-20T00:30:00Z", "per_kwh": 0.18},
                {"start_time": "2026-08-20T01:00:00Z", "per_kwh": 0.15},
                {"start_time": "2026-08-20T01:30:00Z", "per_kwh": 0.35},
            ]
        },
    }

    # Meter and SOC states
    house_power_state = {"entity_id": "sensor.power_meter_house", "state": "850.0"}
    battery_soc_state = {"entity_id": "sensor.battery_state_of_charge", "state": "65.0"}

    async def mock_get_handler(url, headers):
        if "sensor.solcast_pv_forecast" in url:
            return httpx.Response(200, json=solcast_state, request=httpx.Request("GET", url))
        elif "sensor.amber_general_forecast" in url:
            return httpx.Response(200, json=amber_state, request=httpx.Request("GET", url))
        elif "sensor.power_meter_house" in url:
            return httpx.Response(200, json=house_power_state, request=httpx.Request("GET", url))
        elif "sensor.battery_state_of_charge" in url:
            return httpx.Response(200, json=battery_soc_state, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get_handler):
        mappings = {
            "solar_forecast_entity": "sensor.solcast_pv_forecast",
            "buy_price_forecast_entity": "sensor.amber_general_forecast",
            "house_power_entity": "sensor.power_meter_house",
            "battery_soc_entity": "sensor.battery_state_of_charge",
        }

        payload = await client.build_payload_from_entities(
            mappings,
            start_time=datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc),
        )

        assert len(payload.timestamps) == 48
        # First 4 steps match solar and amber mock
        assert payload.solar_forecast[:4] == [0.0, 1500.0, 3800.0, 4200.0]
        assert payload.buy_prices[:4] == [0.22, 0.18, 0.15, 0.35]
        # Subsequent steps forward-fill the last known price
        assert payload.buy_prices[4] == 0.35
        assert payload.actual_load_power_w == 850.0
        assert payload.battery_soc == 65.0


@pytest.mark.asyncio
async def test_sync_ha_and_optimize_endpoint(async_client):
    """Verify /api/v1/ha/sync-and-optimize endpoint."""
    config_store.config.ha_url = "http://ha.local:8123"
    config_store.config.ha_token = "valid_token"

    solcast_state = {
        "entity_id": "sensor.solcast_pv_forecast",
        "state": "2.4",
        "attributes": {
            "detailedForecast": [
                {"period_start": f"2026-08-20T{i:02d}:00:00Z", "pv_estimate": 1.0} for i in range(24)
            ]
        },
    }

    amber_state = {
        "entity_id": "sensor.amber_general_forecast",
        "state": "0.25",
        "attributes": {
            "forecasts": [
                {"start_time": f"2026-08-20T{i:02d}:00:00Z", "per_kwh": 0.20} for i in range(24)
            ]
        },
    }

    async def mock_get_handler(url, headers):
        if "sensor.solcast_pv_forecast" in url:
            return httpx.Response(200, json=solcast_state, request=httpx.Request("GET", url))
        elif "sensor.amber_general_forecast" in url:
            return httpx.Response(200, json=amber_state, request=httpx.Request("GET", url))
        return httpx.Response(200, json={"state": "500"}, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get_handler):
        response = await async_client.post("/api/v1/ha/sync-and-optimize")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "optimized"
        assert len(data["timestamps"]) == 48


def test_generate_load_forecast_from_history_1_to_3_days():
    """Verify generating 1, 2, and 3 day forward-looking load curves from historical sensor readings."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    # Mock 3 days of historical sensor data
    history_records = []
    base_time = datetime(2026, 8, 17, 0, 0, 0, tzinfo=timezone.utc)
    for day in range(3):
        for slot in range(48):  # 30-min intervals
            t = base_time + timedelta(days=day, minutes=30 * slot)
            # Daytime higher load, night lower
            load_val = 400.0 if (t.hour < 6 or t.hour > 22) else 1200.0
            history_records.append({
                "entity_id": "sensor.power_meter_house",
                "state": str(load_val),
                "last_updated": t.isoformat(),
            })

    # Test 1-day horizon (48 steps @ 30m)
    ts_1d, loads_1d = client.generate_load_forecast_from_history(
        history_records=history_records,
        horizon_days=1,
        timestep_minutes=30,
        method="moving_average",
    )
    assert len(ts_1d) == 48
    assert len(loads_1d) == 48
    assert loads_1d[0] < loads_1d[20]  # Night load lower than day load

    # Test 2-day horizon (96 steps @ 30m)
    ts_2d, loads_2d = client.generate_load_forecast_from_history(
        history_records=history_records,
        horizon_days=2,
        timestep_minutes=30,
    )
    assert len(ts_2d) == 96
    assert len(loads_2d) == 96

    # Test 3-day horizon (144 steps @ 30m - max horizon)
    ts_3d, loads_3d = client.generate_load_forecast_from_history(
        history_records=history_records,
        horizon_days=3,
        timestep_minutes=30,
        method="median_profile",
    )
    assert len(ts_3d) == 144
    assert len(loads_3d) == 144

    # Test horizon clamping (> 3 days clamped to 3)
    ts_clamped, loads_clamped = client.generate_load_forecast_from_history(
        history_records=history_records,
        horizon_days=7,  # Request 7 days
        timestep_minutes=30,
    )
    assert len(ts_clamped) == 144  # Clamped strictly to 3 days (144 steps)


@pytest.mark.asyncio
async def test_auto_load_forecast_from_history_when_no_load_sensor():
    """Verify that build_payload_from_entities queries history and generates load forecast when no load sensor is present."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    # Mock historical records returned by /api/history/period/
    mock_history = [[
        {"state": "600.0", "last_updated": f"2026-08-18T{h:02d}:00:00Z"} for h in range(24)
    ]]

    async def mock_get_handler(url, headers):
        if "api/history/period" in url:
            return httpx.Response(200, json=mock_history, request=httpx.Request("GET", url))
        elif "sensor.power_meter_house" in url:
            return httpx.Response(200, json={"state": "650.0"}, request=httpx.Request("GET", url))
        return httpx.Response(200, json={"state": "0"}, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get_handler):
        mappings = {
            "house_power_entity": "sensor.power_meter_house",
        }

        payload = await client.build_payload_from_entities(
            mappings=mappings,
            prediction_horizon_days=2,
            load_history_days=5,
        )

        assert payload.actual_load_power_w == 650.0
        assert payload.load_forecast is not None
        assert len(payload.load_forecast) == 96  # 2 days @ 30m = 96 steps
        assert payload.prediction_horizon_days == 2
        assert payload.load_history_days == 5


@pytest.mark.asyncio
async def test_stitch_multi_day_solar_sensors_comma_separated():
    """Verify that passing 3 separate daily sensors stitches into a single 3-day continuous forecast curve."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    day1_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": f"2026-08-20T{h:02d}:00:00Z", "pv_estimate": 1.5} for h in range(24)
            ]
        }
    }
    day2_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": f"2026-08-21T{h:02d}:00:00Z", "pv_estimate": 2.0} for h in range(24)
            ]
        }
    }
    day3_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": f"2026-08-22T{h:02d}:00:00Z", "pv_estimate": 2.5} for h in range(24)
            ]
        }
    }

    async def mock_get(url, headers):
        if "sensor.solcast_day1" in url:
            return httpx.Response(200, json=day1_state, request=httpx.Request("GET", url))
        elif "sensor.solcast_day2" in url:
            return httpx.Response(200, json=day2_state, request=httpx.Request("GET", url))
        elif "sensor.solcast_day3" in url:
            return httpx.Response(200, json=day3_state, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        input_str = "sensor.solcast_day1, sensor.solcast_day2, sensor.solcast_day3"
        ts, vals = await client.fetch_and_stitch_solar_forecast(input_str, horizon_days=3)

        assert len(ts) == 72  # 3 days @ 24h = 72 intervals
        assert len(vals) == 72
        assert vals[0] == 1500.0   # Day 1 (1.5 kW = 1500 W)
        assert vals[24] == 2000.0  # Day 2 (2.0 kW = 2000 W)
        assert vals[48] == 2500.0  # Day 3 (2.5 kW = 2500 W)


@pytest.mark.asyncio
async def test_multi_array_solar_summation():
    """Verify that dual-array setups (e.g. East + West arrays on same timestamps) are summed together."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    east_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": "2026-08-20T10:00:00Z", "pv_estimate": 1.2},  # 1200W
                {"period_start": "2026-08-20T11:00:00Z", "pv_estimate": 1.5},  # 1500W
            ]
        }
    }
    west_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": "2026-08-20T10:00:00Z", "pv_estimate": 0.8},  # 800W
                {"period_start": "2026-08-20T11:00:00Z", "pv_estimate": 1.1},  # 1100W
            ]
        }
    }

    async def mock_get(url, headers):
        if "sensor.solcast_east" in url:
            return httpx.Response(200, json=east_state, request=httpx.Request("GET", url))
        elif "sensor.solcast_west" in url:
            return httpx.Response(200, json=west_state, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        input_str = "sensor.solcast_east, sensor.solcast_west"
        ts, vals = await client.fetch_and_stitch_solar_forecast(input_str, horizon_days=1)

        assert len(ts) == 2
        # Summed: 1200 + 800 = 2000W, 1500 + 1100 = 2600W
        assert vals[0] == 2000.0
        assert vals[1] == 2600.0


@pytest.mark.asyncio
async def test_auto_discovery_solcast_siblings():
    """Verify that passing single sensor.solcast_forecast_today auto-probes tomorrow and day_3 siblings."""
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    today_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": f"2026-08-20T{h:02d}:00:00Z", "pv_estimate": 1.0} for h in range(24)
            ]
        }
    }
    tomorrow_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": f"2026-08-21T{h:02d}:00:00Z", "pv_estimate": 2.0} for h in range(24)
            ]
        }
    }
    day3_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": f"2026-08-22T{h:02d}:00:00Z", "pv_estimate": 3.0} for h in range(24)
            ]
        }
    }

    async def mock_get(url, headers):
        if "sensor.solcast_forecast_today" in url:
            return httpx.Response(200, json=today_state, request=httpx.Request("GET", url))
        elif "sensor.solcast_forecast_tomorrow" in url:
            return httpx.Response(200, json=tomorrow_state, request=httpx.Request("GET", url))
        elif "sensor.solcast_forecast_day_3" in url or "sensor.solcast_forecast_d3" in url:
            return httpx.Response(200, json=day3_state, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        # User only enters the "today" sensor!
        single_input = "sensor.solcast_forecast_today"
        ts, vals = await client.fetch_and_stitch_solar_forecast(single_input, horizon_days=3)

        assert len(ts) == 72
        assert len(vals) == 72
        assert vals[0] == 1000.0
        assert vals[24] == 2000.0
        assert vals[48] == 3000.0


@pytest.mark.asyncio
async def test_timezone_aware_normalization_utc_and_offset():
    """
    Verify that Solcast UTC timestamps and Amber UTC+10 offset timestamps
    normalize onto the identical canonical UTC timeline.
    """
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    # Solcast in UTC (00:00 UTC = 10:00 AEST)
    solcast_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": "2026-08-20T00:00:00.0000000Z", "pv_estimate": 2.5},
                {"period_start": "2026-08-20T00:30:00.0000000Z", "pv_estimate": 3.0},
            ]
        }
    }

    # Amber in local AEST (+10:00) (10:00 AEST = 00:00 UTC)
    amber_state = {
        "attributes": {
            "forecasts": [
                {"start_time": "2026-08-20T10:00:00+10:00", "per_kwh": 0.25},
                {"start_time": "2026-08-20T10:30:00+10:00", "per_kwh": 0.28},
            ]
        }
    }

    async def mock_get(url, headers):
        if "sensor.solcast" in url:
            return httpx.Response(200, json=solcast_state, request=httpx.Request("GET", url))
        elif "sensor.amber" in url:
            return httpx.Response(200, json=amber_state, request=httpx.Request("GET", url))
        elif "config" in url:
            return httpx.Response(200, json={"time_zone": "Australia/Sydney"}, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        mappings = {
            "solar_forecast_entity": "sensor.solcast",
            "buy_price_forecast_entity": "sensor.amber",
        }
        payload = await client.build_payload_from_entities(
            mappings,
            ha_timezone="Australia/Sydney",
            start_time=datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc),
        )

        assert payload.timestamps[0] == "2026-08-20T00:00:00Z"
        assert payload.timestamps[1] == "2026-08-20T00:30:00Z"
        assert payload.solar_forecast[0] == 2500.0
        assert payload.solar_forecast[1] == 3000.0
        assert payload.buy_prices[0] == 0.25
        assert payload.buy_prices[1] == 0.28


@pytest.mark.asyncio
async def test_amber_express_detailed_forecast_with_variable_steps_and_second_offsets():
    """
    Verify that Amber Express detailedForecast with 5-minute intervals,
    second offsets (:01 start, :00 end), and advanced_price_predicted extracts correctly.
    """
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    amber_express_state = {
        "state": "0.11",
        "attributes": {
            "detailedForecast": [
                {
                    "start_time": "2026-08-20T02:00:01+00:00",
                    "end_time": "2026-08-20T02:05:00+00:00",
                    "duration": 5,
                    "per_kwh": 0.115,
                },
                {
                    "start_time": "2026-08-20T02:05:01+00:00",
                    "end_time": "2026-08-20T02:10:00+00:00",
                    "duration": 5,
                    "per_kwh": 0.125,
                },
                {
                    "start_time": "2026-08-20T02:30:01+00:00",
                    "end_time": "2026-08-20T03:00:00+00:00",
                    "duration": 30,
                    "per_kwh": 0.145,
                },
                {
                    "start_time": "2026-08-20T05:00:01+00:00",
                    "end_time": "2026-08-20T05:30:00+00:00",
                    "duration": 30,
                    "per_kwh": 0.485,
                },
            ]
        }
    }

    async def mock_get(url, headers):
        if "sensor.amber_express" in url:
            return httpx.Response(200, json=amber_express_state, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        mappings = {
            "buy_price_forecast_entity": "sensor.amber_express",
        }
        payload = await client.build_payload_from_entities(
            mappings,
            start_time=datetime(2026, 8, 20, 2, 0, 0, tzinfo=timezone.utc),
        )

        assert len(payload.timestamps) == 48
        # Step 0 (02:00 UTC) matches first 5m slot
        assert payload.buy_prices[0] == 0.115
        # Step 1 (02:30 UTC) matches 30m slot
        assert payload.buy_prices[1] == 0.145
        # Step 6 (05:00 UTC) matches evening spike slot
        assert payload.buy_prices[6] == 0.485


@pytest.mark.asyncio
async def test_realtime_load_blending_into_lead_steps():
    """
    Verify that when actual_house_power is active (e.g. 5000 W hot water heating),
    it blends directly into immediate forward steps of load_forecast.
    """
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    # Real-time house power is 5000 W
    house_power_state = {"state": "5000.0", "attributes": {"unit_of_measurement": "W"}}

    # Solar forecast
    solar_state = {
        "attributes": {
            "detailedForecast": [
                {"period_start": "2026-08-20T00:00:00Z", "pv_estimate": 1.0},
                {"period_start": "2026-08-20T00:30:00Z", "pv_estimate": 1.5},
                {"period_start": "2026-08-20T01:00:00Z", "pv_estimate": 2.0},
                {"period_start": "2026-08-20T01:30:00Z", "pv_estimate": 2.5},
            ]
        }
    }

    async def mock_get(url, headers):
        if "sensor.power_meter" in url:
            return httpx.Response(200, json=house_power_state, request=httpx.Request("GET", url))
        elif "sensor.solcast" in url:
            return httpx.Response(200, json=solar_state, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        mappings = {
            "house_power_entity": "sensor.power_meter",
            "solar_forecast_entity": "sensor.solcast",
        }
        payload = await client.build_payload_from_entities(mappings)

        # Baseline fallback before blending is 5000W (or historical mean).
        # Step 0 should be 5000.0 W (instantaneous live power)
        assert payload.load_forecast[0] == 5000.0
        assert payload.actual_load_power_w == 5000.0


@pytest.mark.asyncio
async def test_deferrable_load_accumulated_hours_and_baseline_deduction():
    """
    Verify that HomeAssistantClient:
    1. Queries history to calculate accumulated runtime today for an active deferrable load.
    2. Subtracts the active deferrable power from house power so baseline load is not double counted.
    """
    client = HomeAssistantClient(base_url="http://ha.local:8123", access_token="token")

    house_power_state = {"state": "5000.0"}
    hot_water_power_state = {"state": "3500.0"}
    hot_water_switch_state = {"state": "on"}

    # 2 hours of ON history today
    history_records = [
        [
            {"last_changed": "2026-08-20T00:00:00Z", "state": "on"},
            {"last_changed": "2026-08-20T02:00:00Z", "state": "on"},
        ]
    ]

    async def mock_get(url, headers):
        if "history" in url:
            return httpx.Response(200, json=history_records, request=httpx.Request("GET", url))
        elif "sensor.house_power" in url:
            return httpx.Response(200, json=house_power_state, request=httpx.Request("GET", url))
        elif "sensor.hot_water_power" in url:
            return httpx.Response(200, json=hot_water_power_state, request=httpx.Request("GET", url))
        elif "switch.hot_water" in url:
            return httpx.Response(200, json=hot_water_switch_state, request=httpx.Request("GET", url))
        elif "config" in url:
            return httpx.Response(200, json={"time_zone": "UTC"}, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    load = DeferrableLoad(
        id="hot_water",
        name="Hot Water",
        nominal_power_w=3500.0,
        required_hours=4.5,
        continuous=True,
        power_sensor_entity_id="sensor.hot_water_power",
        switch_entity_id="switch.hot_water",
    )

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        mappings = {
            "house_power_entity": "sensor.house_power",
        }
        payload = await client.build_payload_from_entities(
            mappings=mappings,
            configured_loads=[load],
            start_time=datetime(2026, 8, 20, 2, 0, 0, tzinfo=timezone.utc),
            ha_timezone="UTC",
        )

        assert len(payload.deferrable_loads) == 1
        updated_load = payload.deferrable_loads[0]
        assert updated_load.is_running is True
        assert updated_load.current_power_w == 3500.0
        # Accumulated hours from history: ~2.0 to ~2.3 hours
        assert updated_load.accumulated_hours_today >= 1.9
        # Remaining hours needed: 4.5 - accumulated
        assert 1.0 <= updated_load.remaining_hours_needed <= 2.6

        # Step 0 baseline load should be house power (5000 W) - deferrable load (3500 W) = 1500 W
        assert payload.load_forecast[0] == 1500.0
