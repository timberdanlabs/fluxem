"""
Unit and integration tests for Module D: Drift-Triggered MPC (Smart Watchdog).
"""

from datetime import datetime, timedelta, timezone
import pytest

from fluxem.ingestion.pipeline import IngestionPipeline
from fluxem.optimization.engine import OptimizationEngine
from fluxem.watchdog.watchdog import DriftWatchdog


def test_initial_sweep_triggers_optimization_when_cache_empty(sample_payload_dict):
    """Verify that an initial run with no cached plan forces a baseline optimization sweep."""
    watchdog = DriftWatchdog()
    assert watchdog.cached_plan is None

    pipeline = IngestionPipeline()
    context = pipeline.ingest(sample_payload_dict)

    decision = watchdog.evaluate(context)
    assert decision.should_reoptimize is True
    assert "No active baseline plan" in decision.reason


def test_watchdog_holds_plan_when_sensors_within_tolerance(sample_payload_dict):
    """
    Verify that when actual sensor measurements are within configured variance thresholds,
    the watchdog holds the existing baseline plan.
    """
    watchdog = DriftWatchdog(
        solar_drift_threshold_pct=25.0,
        price_drift_threshold_pct=20.0,
        load_drift_threshold_pct=30.0,
    )
    pipeline = IngestionPipeline()
    engine = OptimizationEngine()

    # Step 1: Initial baseline run
    context1 = pipeline.ingest(sample_payload_dict)
    initial_plan = engine.optimize(context1)
    watchdog.update_cached_plan(initial_plan)

    # Step 2: 30 minutes later, sensor data arrives with slight variations (< thresholds)
    # Forecast at index 0 in sample_payload: solar=0.0W, baseline load=450.0W, buy_price=0.22
    # In sample_payload, pool_pump (1100W) is running. Total house power = 470W baseline + 1100W pool = 1570W
    payload2 = dict(sample_payload_dict)
    payload2["actual_solar_power_w"] = 0.0       # Exactly 0W
    payload2["actual_load_power_w"] = 1570.0     # 1570W total - 1100W pool = 470W baseline (vs 450W forecast = 4.4% drift < 30%)
    payload2["actual_buy_price"] = 0.23          # 0.23 vs 0.22 forecast (~4.5% drift < 20%)

    context2 = pipeline.ingest(payload2)
    decision = watchdog.evaluate(context2)

    assert decision.should_reoptimize is False
    assert "Holding active baseline plan" in decision.reason
    assert len(decision.breached_metrics) == 0
    assert decision.metrics["load_drift"].is_breached is False
    assert decision.metrics["price_drift"].is_breached is False


def test_solar_drift_trigger():
    """Verify that significant solar variance (e.g. sudden cloud cover) triggers re-optimization."""
    watchdog = DriftWatchdog(solar_drift_threshold_pct=25.0)
    pipeline = IngestionPipeline()
    engine = OptimizationEngine()

    now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    # Forecast predicts 5000W of solar at index 0
    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.20] * 4,
        "solar_forecast": [5000.0, 4800.0, 4000.0, 2000.0],
        "load_forecast": [600.0] * 4,
    }

    # Initial plan
    context1 = pipeline.ingest(payload)
    plan1 = engine.optimize(context1)
    watchdog.update_cached_plan(plan1)

    # Actual observed solar is only 1500W (70% deviation > 25% threshold)
    payload_drift = dict(payload)
    payload_drift["current_solar_power"] = 1500.0

    context2 = pipeline.ingest(payload_drift)
    decision = watchdog.evaluate(context2)

    assert decision.should_reoptimize is True
    assert any("Solar Generation Drift" in b for b in decision.breached_metrics)
    assert decision.metrics["solar_drift"].drift_pct == 70.0
    assert decision.metrics["solar_drift"].is_breached is True


def test_price_drift_trigger():
    """Verify that unexpected spot price spikes trigger re-optimization."""
    watchdog = DriftWatchdog(price_drift_threshold_pct=20.0)
    pipeline = IngestionPipeline()
    engine = OptimizationEngine()

    now = datetime(2026, 8, 20, 18, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.25, 0.25, 0.25, 0.25],
        "solar_forecast": [0.0] * 4,
        "load_forecast": [500.0] * 4,
    }

    context1 = pipeline.ingest(payload)
    plan1 = engine.optimize(context1)
    watchdog.update_cached_plan(plan1)

    # Actual spot price suddenly spikes to $0.60/kWh (> 100% drift)
    payload_spike = dict(payload)
    payload_spike["current_spot_price"] = 0.60

    context2 = pipeline.ingest(payload_spike)
    decision = watchdog.evaluate(context2)

    assert decision.should_reoptimize is True
    assert any("Buy Price Drift" in b for b in decision.breached_metrics)
    assert decision.metrics["price_drift"].is_breached is True


def test_load_drift_trigger_with_decomposed_baseline():
    """
    Verify that unexpected spikes in pure baseline home consumption trigger re-optimization.
    """
    watchdog = DriftWatchdog(load_drift_threshold_pct=30.0)
    pipeline = IngestionPipeline()
    engine = OptimizationEngine()

    now = datetime(2026, 8, 20, 19, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.25] * 4,
        "solar_forecast": [0.0] * 4,
        "load_forecast": [500.0] * 4,  # Forecast 500W baseline
    }

    context1 = pipeline.ingest(payload)
    plan1 = engine.optimize(context1)
    watchdog.update_cached_plan(plan1)

    # Actual household load is 1800W (> 200% drift)
    payload_load_spike = dict(payload)
    payload_load_spike["house_power"] = 1800.0

    context2 = pipeline.ingest(payload_load_spike)
    decision = watchdog.evaluate(context2)

    assert decision.should_reoptimize is True
    assert any("Baseline Load Drift" in b for b in decision.breached_metrics)
    assert decision.metrics["load_drift"].is_breached is True


def test_force_reoptimize_bypasses_all_thresholds(sample_payload_dict):
    """Verify that force_reoptimize=True always executes full re-optimization."""
    watchdog = DriftWatchdog()
    pipeline = IngestionPipeline()
    engine = OptimizationEngine()

    # Pre-populate cache
    context1 = pipeline.ingest(sample_payload_dict)
    plan1 = engine.optimize(context1)
    watchdog.update_cached_plan(plan1)

    # Sensor matches perfectly, but force_reoptimize is set
    payload_forced = dict(sample_payload_dict)
    payload_forced["force_reoptimize"] = True

    context2 = pipeline.ingest(payload_forced)
    decision = watchdog.evaluate(context2, force_reoptimize=True)

    assert decision.should_reoptimize is True
    assert "Forced re-optimization requested" in decision.reason
