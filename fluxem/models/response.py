"""
API response models for FluxEM microservice.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad


class HealthResponse(BaseModel):
    status: str = Field(default="healthy", description="Service health status")
    version: str = Field(..., description="Application version")
    app_name: str = Field(..., description="Application name")
    environment: str = Field(..., description="Environment")
    uptime_seconds: float = Field(..., description="Uptime in seconds")


class ForecastSummary(BaseModel):
    total_solar_kwh: float = Field(..., description="Forecasted solar generation (kWh)")
    total_load_kwh: float = Field(..., description="Forecasted baseline load consumption (kWh)")
    net_deficit_kwh: float = Field(..., description="Net energy deficit (Load - Solar) in kWh")
    min_buy_price: float = Field(..., description="Lowest buy price in horizon ($/kWh)")
    max_buy_price: float = Field(..., description="Peak buy price in horizon ($/kWh)")
    avg_buy_price: float = Field(..., description="Average buy price ($/kWh)")


class IngestionSummaryResponse(BaseModel):
    status: str = Field(default="success", description="Status of ingestion pipeline")
    message: str = Field(..., description="Human-readable description of ingested data")
    total_steps: int = Field(..., description="Number of aligned forecast intervals")
    timestep_minutes: int = Field(..., description="Resolution in minutes per timestep")
    horizon_hours: float = Field(..., description="Horizon span in hours")
    start_time: Optional[str] = Field(None, description="Start timestamp of horizon")
    end_time: Optional[str] = Field(None, description="End timestamp of horizon")
    forecast_summary: ForecastSummary = Field(..., description="Key summary statistics")
    battery: Optional[BatteryState] = Field(None, description="Current battery configuration and state")
    deferrable_loads: List[DeferrableLoad] = Field(default_factory=list, description="Parsed deferrable loads")
    actual_house_power_w: Optional[float] = Field(None, description="Current whole-house power reading (Watts)")
    actual_deferrable_load_power_w: float = Field(default=0.0, description="Current active deferrable loads power (Watts)")
    actual_baseline_load_w: Optional[float] = Field(None, description="Calculated pure baseline home load (house_power - deferrable loads) in Watts")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings or notes")


class OptimizationScheduleResponse(BaseModel):
    status: str = Field(..., description="Optimization status ('optimized', 'held_by_watchdog', 'simulated')")
    execution_time_ms: float = Field(..., description="Execution duration in milliseconds")
    timestamps: List[str] = Field(..., description="ISO-8601 timestamps for each scheduled step")
    solar_forecast_w: List[float] = Field(..., description="Forecasted solar power (W)")
    baseline_load_w: List[float] = Field(..., description="Forecasted baseline home load (W)")
    buy_prices: List[float] = Field(..., description="Import prices ($/kWh)")
    sell_prices: List[float] = Field(..., description="Export prices ($/kWh)")
    deferrable_load_power_w: Dict[str, List[float]] = Field(
        default_factory=dict,
        description="Scheduled power curve in Watts for each deferrable load ID",
    )
    battery_power_w: Optional[List[float]] = Field(
        default=None,
        description="Scheduled battery power curve in Watts (positive = charging, negative = discharging)",
    )
    battery_soc_percent: Optional[List[float]] = Field(
        default=None,
        description="Projected battery SOC % curve",
    )
    grid_import_power_w: Optional[List[float]] = Field(
        default=None,
        description="Projected grid import power in Watts",
    )
    grid_export_power_w: Optional[List[float]] = Field(
        default=None,
        description="Projected grid export power in Watts",
    )
    grid_precharge_power_w: Optional[List[float]] = Field(
        default=None,
        description="Dedicated grid pre-charging power curve in Watts (battery force-charging from grid)",
    )
    arbitrage_export_power_w: Optional[List[float]] = Field(
        default=None,
        description="Dedicated wholesale feed-in arbitrage export power curve in Watts (battery force-discharging to grid)",
    )
    summary: IngestionSummaryResponse = Field(..., description="Summary of input context")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional optimization metadata")
