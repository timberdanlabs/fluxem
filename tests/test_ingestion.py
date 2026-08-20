"""
Unit and integration tests for FluxEM Agnostic Data Ingestion module.
"""

from datetime import datetime, timedelta, timezone
import pytest

from fluxem.ingestion.normalizer import TimeSeriesNormalizer
from fluxem.ingestion.parser import PayloadParser
from fluxem.ingestion.pipeline import IngestionPipeline, StandardizedEnergyContext
from fluxem.ingestion.validator import DataValidator
from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad
from fluxem.models.payload import HomeAssistantPayload


def test_standard_payload_ingestion(sample_payload_dict):
    """Verify that standard 24-step payload is correctly parsed and normalized."""
    pipeline = IngestionPipeline()
    context = pipeline.ingest(sample_payload_dict)

    assert isinstance(context, StandardizedEnergyContext)
    assert context.time_series.total_steps == 24
    assert context.time_series.timestep_minutes == 30
    assert context.time_series.horizon_hours == 12.0
    assert len(context.time_series.solar_powers) == 24
    assert len(context.time_series.load_powers) == 24
    assert len(context.time_series.buy_prices) == 24
    assert len(context.time_series.sell_prices) == 24

    # Verify battery
    assert context.battery is not None
    assert context.battery.soc_percent == 55.0
    assert context.battery.capacity_kwh == 13.5
    assert context.battery.current_energy_kwh == pytest.approx(7.425, rel=1e-3)

    # Verify deferrable loads
    assert len(context.deferrable_loads) == 2
    water_heater = next(load for load in context.deferrable_loads if load.id == "water_heater")
    assert water_heater.continuous is True
    assert water_heater.remaining_hours_needed == 2.5
    assert water_heater.remaining_energy_kwh_needed == pytest.approx(5.50, rel=1e-2)

    pool_pump = next(load for load in context.deferrable_loads if load.id == "pool_pump")
    assert pool_pump.continuous is False
    assert pool_pump.is_running is True
    assert pool_pump.remaining_hours_needed == 2.5

    # Check summary conversion
    summary = context.to_summary_response()
    assert summary.total_steps == 24
    assert summary.forecast_summary.total_solar_kwh > 0
    assert summary.forecast_summary.total_load_kwh > 0


def test_structured_record_payload():
    """Verify ingestion from structured record list (time_series array)."""
    now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    steps = []
    for i in range(10):
        steps.append({
            "timestamp": (now + timedelta(minutes=30 * i)).isoformat(),
            "buy_price": 0.25,
            "sell_price": 0.08,
            "solar_power": 2000.0,
            "load_power": 1000.0,
        })

    payload = {"time_series": steps}
    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    assert context.time_series.total_steps == 10
    assert context.time_series.timestep_minutes == 30
    assert context.time_series.solar_powers[0] == 2000.0
    assert context.time_series.net_loads[0] == -1000.0  # Surplus solar


def test_home_assistant_alias_handling():
    """Verify alias mapping for diverse Home Assistant integrations."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(6)]

    payload_with_aliases = {
        "dates": timestamps,
        "import_prices": [0.20, 0.22, 0.25, 0.30, 0.28, 0.24],
        "feedin_prices": [0.05, 0.05, 0.06, 0.06, 0.05, 0.04],
        "pv_forecast": [0.0, 100.0, 800.0, 2500.0, 1500.0, 0.0],
        "house_power": [400.0, 450.0, 500.0, 600.0, 550.0, 480.0],
        "battery_soc": 80.0,
        "battery_capacity_kwh": 10.0,
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload_with_aliases)

    assert context.time_series.total_steps == 6
    assert context.time_series.timestep_minutes == 60
    assert context.battery is not None
    assert context.battery.soc_percent == 80.0
    assert context.battery.capacity_kwh == 10.0


def test_unit_conversions():
    """Verify conversion from kW to W and c/kWh to $/kWh."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [25.0, 30.0, 35.0, 20.0],  # cents/kWh
        "sell_prices": [8.0, 8.0, 6.0, 5.0],     # cents/kWh
        "solar_forecast": [0.0, 1.5, 4.2, 2.0],   # kW
        "load_forecast": [0.6, 0.8, 1.2, 0.5],    # kW
        "unit_load": "kW",
        "unit_solar": "kW",
        "unit_price": "c/kWh",
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    # Prices converted to $/kWh
    assert context.time_series.buy_prices[0] == 0.25
    assert context.time_series.sell_prices[0] == 0.08

    # Powers converted to Watts
    assert context.time_series.solar_powers[1] == 1500.0
    assert context.time_series.load_powers[0] == 600.0


def test_nan_imputation_and_non_monotonic_sorting():
    """Verify NaN cleaning and out-of-order timestamp sorting."""
    t1 = datetime(2026, 8, 20, 2, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 20, 1, 0, 0, tzinfo=timezone.utc)  # Out of order
    t3 = datetime(2026, 8, 20, 3, 0, 0, tzinfo=timezone.utc)

    payload = {
        "timestamps": [t1.isoformat(), t2.isoformat(), t3.isoformat()],
        "buy_prices": [0.30, 0.20, None],  # Missing price at t3
        "sell_prices": [0.05, None, 0.05],
        "solar_forecast": [1000.0, None, 3000.0],
        "load_forecast": [500.0, 600.0, None],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    assert context.time_series.total_steps == 3
    # Sorted chronologically: t2 (1:00), t1 (2:00), t3 (3:00)
    assert context.time_series.timestamps[0] == t2
    assert context.time_series.timestamps[1] == t1
    assert context.time_series.timestamps[2] == t3
    # NaN at t3 filled with previous value (0.30)
    assert context.time_series.buy_prices[2] == 0.30


def test_target_timestep_resampling():
    """Verify resampling from 60-min native resolution to 30-min resolution."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(5)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.20, 0.25, 0.30, 0.22, 0.18],
        "solar_forecast": [0.0, 1000.0, 3000.0, 1500.0, 0.0],
        "load_forecast": [500.0, 600.0, 700.0, 600.0, 500.0],
        "target_timestep_minutes": 30,
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    # 4 hours span @ 30 min intervals = 9 points (0h, 0.5h, 1.0h, ..., 4.0h)
    assert context.time_series.timestep_minutes == 30
    assert context.time_series.total_steps == 9


def test_battery_fraction_to_percent_conversion():
    """Verify that battery SOC passed as a fraction (0.75) is converted to percentage (75%)."""
    battery = BatteryState(
        soc_percent=0.75,
        capacity_kwh=10.0,
        min_soc_percent=0.20,
    )
    assert battery.soc_percent == 75.0
    assert battery.min_soc_percent == 20.0
    assert battery.usable_capacity_kwh == 8.0
    assert battery.available_discharge_energy_kwh == 5.5
    assert battery.available_charge_energy_kwh == 2.5


def test_empty_payload_raises_error():
    """Verify validation error when payload contains no time data."""
    pipeline = IngestionPipeline()
    with pytest.raises(ValueError, match="Payload must contain"):
        pipeline.ingest({})


def test_loads_energy_resolution_and_satisfaction():
    """Verify that required_kwh is properly converted to required_hours and satisfaction check works."""
    load = DeferrableLoad(
        id="heat_pump",
        nominal_power_w=2000.0,
        required_kwh=6.0,  # 6.0 kWh / 2.0 kW = 3.0 hours
        accumulated_hours_today=3.0,
    )
    assert load.required_hours == 3.0
    assert load.name == "Heat Pump"
    assert load.remaining_hours_needed == 0.0
    assert load.is_satisfied is True


def test_battery_validation_error():
    """Verify error raised when min_soc > max_soc."""
    with pytest.raises(ValueError, match="cannot exceed max_soc_percent"):
        BatteryState(
            soc_percent=50.0,
            capacity_kwh=10.0,
            min_soc_percent=80.0,
            max_soc_percent=20.0,
        )


def test_validator_negative_clamps_and_battery_warnings():
    """Verify validator clamps negative solar/load and logs battery warnings."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.20, 0.20, 0.20, 0.20],
        "solar_forecast": [-50.0, 100.0, 200.0, -10.0],  # Negative solar
        "load_forecast": [-100.0, 500.0, 600.0, 500.0],  # Negative load
        "battery": {
            "soc_percent": 5.0,  # Below min_soc (10%)
            "capacity_kwh": 10.0,
            "min_soc_percent": 10.0,
            "max_charge_power_w": 0.0,  # Warning: <= 0
            "max_discharge_power_w": 0.0,  # Warning: <= 0
        },
        "deferrable_loads": [
            {
                "id": "pool",
                "nominal_power_w": 1000.0,
                "required_hours": 2.0,
                "accumulated_hours_today": 2.5,  # Already satisfied
            },
            {
                "id": "pool",  # Duplicate ID
                "nominal_power_w": 1000.0,
                "required_hours": 2.0,
            },
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    # Clamping
    assert context.time_series.solar_powers[0] == 0.0
    assert context.time_series.solar_powers[3] == 0.0
    assert context.time_series.load_powers[0] == 0.0

    # Warnings recorded
    warning_text = " ".join(context.warnings)
    assert "Negative solar power values detected" in warning_text
    assert "Negative home load values detected" in warning_text
    assert "below configured min_soc" in warning_text
    assert "max_charge_power_w is <= 0" in warning_text
    assert "Duplicate deferrable load ID" in warning_text
    assert "already been satisfied today" in warning_text


def test_missing_optional_arrays_use_safe_defaults():
    """Verify fallback defaults when solar, sell_prices, or load forecasts are omitted."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.20, 0.22, 0.25, 0.28],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    assert context.time_series.sell_prices == [0.0, 0.0, 0.0, 0.0]
    assert context.time_series.solar_powers == [0.0, 0.0, 0.0, 0.0]
    assert context.time_series.load_powers == [500.0, 500.0, 500.0, 500.0]
    assert any("sell_prices not provided" in w for w in context.warnings)
    assert any("solar_forecast not provided" in w for w in context.warnings)
    assert any("load_forecast not provided" in w for w in context.warnings)


def test_deferrable_load_deduction_from_house_power():
    """
    Verify that active deferrable load consumption is automatically deducted
    from whole-home house_power to isolate the pure baseline home demand.
    """
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.25, 0.25, 0.25, 0.25],
        "house_power": 4500.0,  # 4500W whole-home consumption
        "deferrable_loads": [
            {
                "id": "water_heater",
                "name": "Heat Pump Hot Water",
                "nominal_power_w": 3700.0,
                "current_power_w": 3700.0,  # Dedicated smart meter reporting 3700W
                "required_hours": 3.0,
                "is_running": True,
                "is_included_in_total_load": True,
            }
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    # 4500W - 3700W = 800W pure baseline load
    assert context.active_deferrable_power_w == 3700.0
    assert context.actual_baseline_load_w == 800.0
    assert context.actual_sensors["total_house_power_w"] == 4500.0
    assert context.actual_sensors["deferrable_load_power_w"] == 3700.0
    assert context.actual_sensors["baseline_load_power_w"] == 800.0

    summary = context.to_summary_response()
    assert summary.actual_house_power_w == 4500.0
    assert summary.actual_deferrable_load_power_w == 3700.0
    assert summary.actual_baseline_load_w == 800.0
    assert any("Deducted 3700.0 W" in w for w in context.warnings)


def test_multiple_deferrable_loads_deduction_and_exclusion():
    """Verify multiple active loads deduction and exclusion when is_included_in_total_load is False."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.25, 0.25, 0.25, 0.25],
        "current_house_power": 6000.0,
        "deferrable_loads": [
            {
                "id": "water_heater",
                "nominal_power_w": 3700.0,
                "is_running": True,  # Uses nominal power
                "required_hours": 3.0,
                "is_included_in_total_load": True,
            },
            {
                "id": "pool_pump",
                "nominal_power_w": 1200.0,
                "current_power_w": 1100.0,  # Measured power
                "required_hours": 4.0,
                "is_included_in_total_load": True,
            },
            {
                "id": "external_shed",
                "nominal_power_w": 2000.0,
                "current_power_w": 2000.0,
                "required_hours": 2.0,
                "is_included_in_total_load": False,  # On separate unmetered subpanel
            },
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    # Active included: 3700W (water heater) + 1100W (pool pump) = 4800W
    # Baseline: 6000W - 4800W = 1200W
    assert context.active_deferrable_power_w == 4800.0
    assert context.actual_baseline_load_w == 1200.0
