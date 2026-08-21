"""
Telemetry, Plan of Record, and Dashboard Data Models for FluxEM v2.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from fluxem.models.response import IngestionSummaryResponse, OptimizationScheduleResponse


class TimestepActual(BaseModel):
    """Realized actual telemetry recorded for a specific interval timestamp."""
    timestamp: str = Field(..., description="ISO-8601 timestamp")
    solar_power_w: Optional[float] = Field(None, description="Actual realized solar power (Watts)")
    house_power_w: Optional[float] = Field(None, description="Actual whole-home power (Watts)")
    baseline_load_w: Optional[float] = Field(None, description="Actual pure baseline load (Watts)")
    battery_soc_percent: Optional[float] = Field(None, description="Actual battery state of charge (%)")
    battery_power_w: Optional[float] = Field(None, description="Actual battery net power (Watts)")
    deferrable_load_power_w: Dict[str, float] = Field(
        default_factory=dict,
        description="Actual measured power for each deferrable appliance ID",
    )
    buy_price: Optional[float] = Field(None, description="Actual import electricity price ($/kWh)")
    sell_price: Optional[float] = Field(None, description="Actual export feed-in price ($/kWh)")
    grid_import_power_w: Optional[float] = Field(None, description="Actual grid import power (Watts)")
    grid_export_power_w: Optional[float] = Field(None, description="Actual grid export power (Watts)")


class PlanAdherenceMetrics(BaseModel):
    """Statistical variance and adherence comparing Plan of Record against Realized Actuals."""
    elapsed_steps: int = Field(default=0, description="Number of elapsed 30-min intervals today")
    current_step_index: int = Field(default=0, description="Current timestep index in today's schedule")
    current_timestamp: str = Field(default="", description="Current interval ISO timestamp")

    # Solar Generation Metrics
    actual_solar_kwh: float = Field(default=0.0, description="Realized solar generation accumulated today (kWh)")
    planned_solar_kwh: float = Field(default=0.0, description="Planned solar generation for elapsed period today (kWh)")
    full_day_planned_solar_kwh: float = Field(default=0.0, description="Total 24h planned solar generation (kWh)")
    solar_delta_kwh: float = Field(default=0.0, description="Actual solar minus planned solar (kWh)")
    solar_drift_pct: float = Field(default=0.0, description="Solar percentage drift from plan")

    # Household Consumption Metrics
    actual_load_kwh: float = Field(default=0.0, description="Realized baseline consumption today (kWh)")
    planned_load_kwh: float = Field(default=0.0, description="Planned baseline consumption for elapsed period today (kWh)")
    full_day_planned_load_kwh: float = Field(default=0.0, description="Total 24h planned baseline consumption (kWh)")
    load_delta_kwh: float = Field(default=0.0, description="Actual load minus planned load (kWh)")
    load_drift_pct: float = Field(default=0.0, description="Load percentage drift from plan")

    # Battery State Metrics
    actual_battery_soc: Optional[float] = Field(None, description="Current actual battery SOC (%)")
    planned_battery_soc: Optional[float] = Field(None, description="Baseline planned battery SOC at current step (%)")
    battery_soc_delta: Optional[float] = Field(None, description="Actual SOC minus planned SOC (%)")

    # Status & Locking
    has_baseline_plan: bool = Field(default=False, description="Whether a baseline plan of record exists for today")
    is_baseline_locked: bool = Field(default=False, description="Whether baseline plan was explicitly locked by user")
    baseline_established_at: Optional[str] = Field(None, description="Timestamp when baseline plan was established")
    watchdog_status: str = Field(default="nominal", description="Current watchdog status (nominal, holding_plan, reoptimized)")
    watchdog_reason: str = Field(default="", description="Reason for latest watchdog action")


class DashboardDataResponse(BaseModel):
    """Complete aggregated payload for the v2 WebUI Dashboard."""
    timezone: str = Field(default="UTC", description="Resolved local timezone")
    current_time: str = Field(..., description="Current ISO timestamp")
    today_date: str = Field(..., description="Current local date (YYYY-MM-DD)")
    horizon_days: int = Field(default=1, description="Configured prediction horizon in days")
    current_step_index: int = Field(default=0, description="Current step index within today's 48 intervals")
    baseline_plan: Optional[OptimizationScheduleResponse] = Field(None, description="Today's frozen Baseline Plan of Record")
    active_schedule: Optional[OptimizationScheduleResponse] = Field(None, description="Current active / re-optimized schedule")
    actuals: Dict[str, TimestepActual] = Field(default_factory=dict, description="Realized actuals indexed by ISO timestamp")
    adherence: PlanAdherenceMetrics = Field(default_factory=PlanAdherenceMetrics, description="Plan vs. reality adherence summary")
    config_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary of active configuration settings")
