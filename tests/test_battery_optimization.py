"""
Unit and integration tests for Module C: Intelligent Grid Pre-Charging & Dynamic Battery Arbitrage.
"""

from datetime import datetime, timedelta, timezone
import pytest

from fluxem.ingestion.pipeline import IngestionPipeline
from fluxem.models.battery import BatteryState
from fluxem.optimization.battery import BatteryScheduler
from fluxem.optimization.engine import OptimizationEngine


def test_standard_solar_charging_and_load_discharging():
    """
    Verify basic solar self-consumption: excess solar charges the battery,
    and evening home consumption discharges the battery down to min_soc_percent.
    """
    now = datetime(2026, 8, 20, 10, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(6)]

    # Solar excess at hour 0-2 (4000W - 1000W = 3000W surplus)
    # Evening deficit at hour 3-5 (0W solar - 2500W load = 2500W deficit)
    solar_forecast = [4000.0, 4000.0, 4000.0, 0.0, 0.0, 0.0]
    load_forecast = [1000.0, 1000.0, 1000.0, 2500.0, 2500.0, 2500.0]
    buy_prices = [0.25] * 6
    sell_prices = [0.05] * 6

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "sell_prices": sell_prices,
        "solar_forecast": solar_forecast,
        "load_forecast": load_forecast,
        "battery": {
            "soc_percent": 20.0,
            "capacity_kwh": 10.0,
            "max_charge_power_w": 3000.0,
            "max_discharge_power_w": 3000.0,
            "min_soc_percent": 10.0,
            "max_soc_percent": 100.0,
        },
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    # Battery power: positive during solar surplus (charging), negative during deficit (discharging)
    batt_power = response.battery_power_w
    assert batt_power is not None
    assert batt_power[0] > 0   # Charging from solar
    assert batt_power[1] > 0   # Charging from solar
    assert batt_power[3] < 0   # Discharging for evening load

    # Verify SOC rises then discharges
    soc = response.battery_soc_percent
    assert soc is not None
    assert soc[2] > soc[0]     # Higher after solar charging
    assert soc[-1] >= 10.0     # Never drops below min_soc (10%)


def test_intelligent_grid_precharging_before_peak_prices():
    """
    Verify look-ahead grid pre-charging: When battery would otherwise be exhausted
    during an expensive evening price spike, FluxEM pre-charges from the grid during
    the cheap early morning window.
    """
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(8)]

    # Price profile:
    # Hours 0-1: Cheap off-peak ($0.10/kWh)
    # Hours 2-5: Shoulder ($0.25/kWh)
    # Hours 6-7: Extreme Evening Peak ($0.65/kWh)
    buy_prices = [0.10, 0.10, 0.25, 0.25, 0.25, 0.25, 0.65, 0.65]
    sell_prices = [0.04] * 8

    # No solar generation in this test
    solar_forecast = [0.0] * 8
    # High evening consumption (3500W at peak hours 6 and 7)
    load_forecast = [500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 3500.0, 3500.0]

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "sell_prices": sell_prices,
        "solar_forecast": solar_forecast,
        "load_forecast": load_forecast,
        "battery": {
            "soc_percent": 10.0,  # Starts at minimum reserve SOC (10%)
            "capacity_kwh": 10.0,
            "max_charge_power_w": 4000.0,
            "max_discharge_power_w": 4000.0,
            "min_soc_percent": 10.0,
            "max_soc_percent": 100.0,
            "round_trip_efficiency": 0.90,
        },
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    # Grid pre-charging must occur during cheap hours (index 0 or 1)
    precharge_power = response.metadata["battery_summary"]["grid_precharge_power_w"]
    assert sum(precharge_power[:2]) > 0
    assert response.metadata["battery_summary"]["grid_precharged_kwh"] > 0

    # During peak hours (6, 7), the battery discharges to cover the 3500W load instead of importing
    batt_power = response.battery_power_w
    assert batt_power[6] < 0
    assert batt_power[7] < 0
    assert any("Scheduled" in w and "grid pre-charge" in w for w in response.summary.warnings)


def test_dynamic_export_arbitrage_enabled():
    """
    Verify dynamic wholesale export arbitrage: When enable_export_arbitrage=True,
    charges from the grid at cheap import rates and exports to the grid at high feed-in price spikes.
    """
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(8)]

    # Buy price is cheap at hour 1 ($0.08/kWh)
    buy_prices = [0.20, 0.08, 0.20, 0.20, 0.20, 0.20, 0.20, 0.20]
    # Sell price spikes massively at hour 6 ($0.55/kWh feed-in tariff)
    sell_prices = [0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.55, 0.05]

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "sell_prices": sell_prices,
        "solar_forecast": [0.0] * 8,
        "load_forecast": [300.0] * 8,
        "enable_export_arbitrage": True,
        "min_arbitrage_profit_per_kwh": 0.03,
        "battery": {
            "soc_percent": 30.0,
            "capacity_kwh": 10.0,
            "max_charge_power_w": 5000.0,
            "max_discharge_power_w": 5000.0,
            "min_soc_percent": 10.0,
            "max_soc_percent": 100.0,
            "round_trip_efficiency": 0.90,
        },
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    # Grid export power at hour 6 must be positive (discharging to grid)
    assert response.grid_export_power_w[6] > 0
    # Arbitrage exported energy recorded
    assert response.metadata["battery_summary"]["arbitrage_exported_kwh"] > 0
    assert any("Export Arbitrage:" in w for w in response.summary.warnings)


def test_dynamic_export_arbitrage_disabled_by_default():
    """
    Verify that when enable_export_arbitrage is False (default),
    no grid export arbitrage is scheduled even with high feed-in spikes.
    """
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(6)]

    buy_prices = [0.05, 0.05, 0.20, 0.20, 0.20, 0.20]
    sell_prices = [0.02, 0.02, 0.02, 0.02, 0.60, 0.02]  # High sell price at index 4

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "sell_prices": sell_prices,
        "solar_forecast": [0.0] * 6,
        "load_forecast": [400.0] * 6,
        "enable_export_arbitrage": False,  # Explicitly disabled
        "battery": {
            "soc_percent": 50.0,
            "capacity_kwh": 10.0,
            "min_soc_percent": 10.0,
        },
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    # No arbitrage export should occur
    assert response.metadata["battery_summary"]["arbitrage_exported_kwh"] == 0.0
    assert not any("Export Arbitrage:" in w for w in response.summary.warnings)
