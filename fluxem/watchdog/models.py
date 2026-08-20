"""
Data models for Module D: Drift-Triggered MPC (Smart Watchdog).
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DriftMetric(BaseModel):
    """Variance comparison metric between observed sensor and forecasted value."""
    name: str = Field(..., description="Name of the metric (e.g. 'solar_drift', 'load_drift', 'price_drift')")
    actual_value: Optional[float] = Field(None, description="Actual observed real-time sensor measurement")
    forecast_value: Optional[float] = Field(None, description="Forecasted / planned value for the current timestamp")
    drift_pct: float = Field(default=0.0, description="Calculated percentage drift (%)")
    threshold_pct: float = Field(..., description="Configured drift tolerance threshold (%)")
    is_breached: bool = Field(default=False, description="True if drift percentage exceeds threshold")
    unit: str = Field(default="", description="Measurement unit (e.g. 'W', '$/kWh', '%')")


class WatchdogDecision(BaseModel):
    """Outcome of the drift evaluation."""
    should_reoptimize: bool = Field(..., description="True if full re-optimization should execute")
    reason: str = Field(..., description="Human-readable rationale for the decision")
    metrics: Dict[str, DriftMetric] = Field(default_factory=dict, description="Detailed drift metrics evaluated")
    breached_metrics: List[str] = Field(default_factory=list, description="List of metric names that crossed thresholds")
