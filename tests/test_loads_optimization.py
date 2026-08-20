"""
Unit and integration tests for Module B: Flexible Deferrable Load Management.
"""

from datetime import datetime, timedelta, timezone
import pytest

from fluxem.ingestion.pipeline import IngestionPipeline
from fluxem.models.loads import DeferrableLoad
from fluxem.optimization.engine import OptimizationEngine
from fluxem.optimization.loads import DeferrableLoadScheduler


def test_continuous_load_picks_cheapest_contiguous_block(sample_payload_dict):
    """
    Verify that an inactive continuous load (e.g. heat pump hot water)
    is scheduled in a single unbroken contiguous block in the lowest-cost solar/price window.
    """
    pipeline = IngestionPipeline()
    context = pipeline.ingest(sample_payload_dict)

    scheduler = DeferrableLoadScheduler()
    schedules, combined_power, warnings = scheduler.schedule_all(
        loads=context.deferrable_loads,
        time_series=context.time_series,
    )

    water_heater_schedule = schedules["water_heater"]
    # 2.5 hours remaining needed @ 30 min intervals = 5 steps
    active_indices = [i for i, p in enumerate(water_heater_schedule) if p > 0]
    assert len(active_indices) == 5

    # Check contiguous block
    for k in range(len(active_indices) - 1):
        assert active_indices[k + 1] == active_indices[k] + 1

    # In sample_payload, midday has high solar (up to 6400W) and low buy price (0.05-0.08)
    # The active indices should be in midday (between steps 10 and 17)
    assert min(active_indices) >= 10
    assert max(active_indices) <= 17


def test_continuous_load_mid_cycle_running_state_preservation():
    """
    Verify that when a continuous load is actively running (is_running=True),
    the scheduler continues running it immediately from step 0 without gaps.
    """
    now = datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(12)]

    # Expensive price at step 0, cheap at step 6
    buy_prices = [0.40, 0.40, 0.40, 0.30, 0.20, 0.15, 0.10, 0.10, 0.15, 0.20, 0.30, 0.40]

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "solar_forecast": [0.0] * 12,
        "load_forecast": [400.0] * 12,
        "deferrable_loads": [
            {
                "id": "hot_water",
                "nominal_power_w": 2400.0,
                "required_hours": 3.0,
                "accumulated_hours_today": 1.0,  # 2.0h remaining = 4 steps
                "continuous": True,
                "is_running": True,  # Actively running right now
            }
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    hw_schedule = response.deferrable_load_power_w["hot_water"]
    active_indices = [i for i, p in enumerate(hw_schedule) if p > 0]

    # Must be exactly steps 0, 1, 2, 3 (immediate continuation)
    assert active_indices == [0, 1, 2, 3]
    assert any("actively running. Enforcing contiguous block from step 0" in w for w in response.summary.warnings)


def test_flexible_load_splits_across_cheapest_intervals():
    """
    Verify that a flexible load splits across individual lowest-price / highest-solar intervals
    when max_starts_per_day is not constrained.
    """
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(8)]

    # Non-contiguous cheap hours at index 1, index 4, and index 6
    buy_prices = [0.35, 0.10, 0.35, 0.40, 0.08, 0.30, 0.05, 0.45]

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "deferrable_loads": [
            {
                "id": "pool_pump",
                "nominal_power_w": 1000.0,
                "required_hours": 3.0,  # 3 hours @ 60m = 3 steps
                "continuous": False,
                "max_starts_per_day": 3,
            }
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    pool_schedule = response.deferrable_load_power_w["pool_pump"]
    active_indices = [i for i, p in enumerate(pool_schedule) if p > 0]

    # Cheapest prices are at index 6 (0.05), index 4 (0.08), and index 1 (0.10)
    assert sorted(active_indices) == [1, 4, 6]


def test_flexible_load_respects_max_starts_constraint():
    """
    Verify dynamic programming start-clustering when max_starts_per_day limits start cycles.
    """
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(10)]

    # Price pattern:
    # steps 0-1: 0.20, 0.20
    # steps 2-3: 0.50, 0.50 (spike)
    # steps 4-5: 0.15, 0.15 (dip)
    # step 6: 0.50 (spike)
    # steps 7-8: 0.10, 0.10 (dip)
    # step 9: 0.50
    buy_prices = [0.20, 0.20, 0.50, 0.50, 0.15, 0.15, 0.50, 0.10, 0.10, 0.50]

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "deferrable_loads": [
            {
                "id": "ev_charge",
                "nominal_power_w": 7000.0,
                "required_hours": 2.0,  # 4 steps @ 30m
                "continuous": False,
                "max_starts_per_day": 2,  # Maximum 2 distinct start/stop cycles
            }
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    ev_schedule = response.deferrable_load_power_w["ev_charge"]
    active_indices = [i for i, p in enumerate(ev_schedule) if p > 0]
    assert len(active_indices) == 4

    # Count start events (where index is 0 or prev index != current - 1)
    starts = sum(1 for k in range(len(active_indices)) if k == 0 or active_indices[k] != active_indices[k - 1] + 1)
    assert starts <= 2


def test_time_window_constraints():
    """Verify that load scheduling strictly respects window_start_time and window_end_time."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(24)]

    # Midnight (00:00 to 06:00) is cheap, but window restricts to 10:00 - 16:00
    buy_prices = [0.05] * 6 + [0.30] * 4 + [0.15] * 6 + [0.40] * 8

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "deferrable_loads": [
            {
                "id": "solar_diverter",
                "nominal_power_w": 1500.0,
                "required_hours": 3.0,
                "continuous": True,
                "window_start_time": "10:00",
                "window_end_time": "16:00",
            }
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    schedule = response.deferrable_load_power_w["solar_diverter"]
    active_indices = [i for i, p in enumerate(schedule) if p > 0]
    assert len(active_indices) == 3

    # All active indices must fall between hour 10 and hour 16
    for idx in active_indices:
        hour = context.time_series.timestamps[idx].hour
        assert 10 <= hour <= 16


def test_multi_load_priority_solar_stacking():
    """
    Verify that higher priority loads get first claim on excess solar generation,
    while lower priority loads consume remaining solar or grid power.
    """
    now = datetime(2026, 8, 20, 10, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(4)]

    # Solar excess is 2000W at hour 1
    solar_forecast = [0.0, 2500.0, 0.0, 0.0]
    load_forecast = [500.0, 500.0, 500.0, 500.0]  # Excess at hour 1 = 2000W
    buy_prices = [0.30, 0.30, 0.30, 0.30]
    sell_prices = [0.05, 0.05, 0.05, 0.05]

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "sell_prices": sell_prices,
        "solar_forecast": solar_forecast,
        "load_forecast": load_forecast,
        "deferrable_loads": [
            {
                "id": "high_pri_hot_water",
                "nominal_power_w": 2000.0,
                "required_hours": 1.0,
                "priority": 2,  # Higher priority
            },
            {
                "id": "low_pri_pool",
                "nominal_power_w": 1000.0,
                "required_hours": 1.0,
                "priority": 1,  # Lower priority
            },
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    hw_schedule = response.deferrable_load_power_w["high_pri_hot_water"]
    # High priority should capture the 2000W excess solar at index 1
    assert hw_schedule[1] == 2000.0


def test_already_satisfied_load_produces_zero_schedule():
    """Verify that a load that has already completed its daily runtime produces zero power schedule."""
    now = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = [(now + timedelta(hours=i)).isoformat() for i in range(4)]

    payload = {
        "timestamps": timestamps,
        "buy_prices": [0.20, 0.20, 0.20, 0.20],
        "deferrable_loads": [
            {
                "id": "completed_heater",
                "nominal_power_w": 2000.0,
                "required_hours": 2.0,
                "accumulated_hours_today": 2.5,  # Exceeded required hours
            }
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    schedule = response.deferrable_load_power_w["completed_heater"]
    assert schedule == [0.0, 0.0, 0.0, 0.0]
    assert any("already completed required runtime today" in w for w in response.summary.warnings)


def test_multi_day_deferrable_load_scheduling():
    """
    Verify that across a multi-day horizon (48 hours):
    1. Day 1 (today) schedules remaining daily hours (e.g. 4.5h - 2.0h accumulated = 2.5h remaining).
    2. Day 2 (tomorrow) schedules fresh full daily quota (4.5h).
    3. A second load that already completed today (0h remaining today) gets scheduled fresh for tomorrow (2.0h).
    """
    now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    # 48 hours @ 30 min intervals = 96 steps
    timestamps = [(now + timedelta(minutes=30 * i)).isoformat() for i in range(96)]
    buy_prices = [0.25] * 96

    payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "solar_forecast": [0.0] * 96,
        "load_forecast": [500.0] * 96,
        "deferrable_loads": [
            {
                "id": "hot_water",
                "name": "Hot Water",
                "nominal_power_w": 3600.0,
                "required_hours": 4.5,
                "accumulated_hours_today": 2.0,  # 2.5h remaining today (5 steps)
                "continuous": True,
            },
            {
                "id": "pool_pump",
                "name": "Pool Pump",
                "nominal_power_w": 1200.0,
                "required_hours": 2.0,
                "accumulated_hours_today": 2.5,  # 0h remaining today, but 2h (4 steps) tomorrow
                "continuous": True,
            },
        ],
    }

    pipeline = IngestionPipeline()
    context = pipeline.ingest(payload)

    engine = OptimizationEngine()
    response = engine.optimize(context)

    hw_sched = response.deferrable_load_power_w["hot_water"]
    pp_sched = response.deferrable_load_power_w["pool_pump"]

    # Hot Water: Day 1 (5 steps @ 30m = 2.5h) + Day 2 (9 steps @ 30m = 4.5h) + Day 3 partial (up to 9 steps)
    hw_active_steps = sum(1 for p in hw_sched if p > 0)
    assert hw_active_steps >= 14  # At least 5 (Day 1) + 9 (Day 2) = 14 steps (7.0h)

    # Pool Pump: Day 1 (0 steps today) + Day 2 (4 steps @ 30m = 2.0h) + Day 3 partial
    pp_active_steps = sum(1 for p in pp_sched if p > 0)
    assert pp_active_steps >= 4  # At least 4 steps (2.0h) tomorrow

