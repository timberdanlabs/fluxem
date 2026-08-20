"""
Data Ingestion Pipeline orchestrating Parser, Validator, and Normalizer.
Produces a StandardizedEnergyContext ready for downstream optimization and watchdog modules.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import pandas as pd

from fluxem.config import settings
from fluxem.ingestion.normalizer import TimeSeriesNormalizer
from fluxem.ingestion.parser import PayloadParser
from fluxem.ingestion.validator import DataValidator
from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad
from fluxem.models.payload import HomeAssistantPayload
from fluxem.models.response import ForecastSummary, IngestionSummaryResponse
from fluxem.models.time_series import ProcessedTimeSeriesData
from fluxem.storage import config_store


@dataclass
class StandardizedEnergyContext:
    """
    Complete, validated, and normalized context ready for optimization algorithms.
    """
    time_series: ProcessedTimeSeriesData
    battery: Optional[BatteryState] = None
    deferrable_loads: List[DeferrableLoad] = field(default_factory=list)
    timestep_minutes: int = 30
    horizon_hours: float = 24.0
    actual_sensors: Dict[str, Optional[float]] = field(default_factory=dict)
    active_deferrable_power_w: float = 0.0
    actual_baseline_load_w: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    ingestion_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_summary_response(self) -> IngestionSummaryResponse:
        """Converts context into an API summary response."""
        total_solar = self.time_series.total_solar_energy_kwh
        total_load = self.time_series.total_load_energy_kwh
        net_deficit = max(0.0, total_load - total_solar)

        forecast_summary = ForecastSummary(
            total_solar_kwh=round(total_solar, 3),
            total_load_kwh=round(total_load, 3),
            net_deficit_kwh=round(net_deficit, 3),
            min_buy_price=round(self.time_series.min_buy_price, 4),
            max_buy_price=round(self.time_series.max_buy_price, 4),
            avg_buy_price=round(self.time_series.avg_buy_price, 4),
        )

        return IngestionSummaryResponse(
            status="success" if not self.warnings else "warning",
            message=(
                f"Successfully ingested {self.time_series.total_steps} timesteps "
                f"({self.time_series.horizon_hours:.1f}h horizon at {self.time_series.timestep_minutes}m resolution)."
            ),
            total_steps=self.time_series.total_steps,
            timestep_minutes=self.time_series.timestep_minutes,
            horizon_hours=round(self.time_series.horizon_hours, 2),
            start_time=self.time_series.timestamps_iso[0] if self.time_series.timestamps_iso else None,
            end_time=self.time_series.timestamps_iso[-1] if self.time_series.timestamps_iso else None,
            forecast_summary=forecast_summary,
            battery=self.battery,
            deferrable_loads=self.deferrable_loads,
            actual_house_power_w=self.actual_sensors.get("total_house_power_w"),
            actual_deferrable_load_power_w=self.active_deferrable_power_w,
            actual_baseline_load_w=self.actual_baseline_load_w,
            warnings=self.warnings,
        )


class IngestionPipeline:
    """
    Main entrypoint for Agnostic Data Ingestion.
    """

    def __init__(
        self,
        default_timestep_minutes: Optional[int] = None,
        min_horizon_hours: Optional[float] = None,
        max_horizon_hours: Optional[float] = None,
    ):
        self.default_timestep_minutes = default_timestep_minutes or settings.default_timestep_minutes
        self.min_horizon_hours = min_horizon_hours or float(settings.min_horizon_hours)
        self.max_horizon_hours = max_horizon_hours or float(settings.max_horizon_hours)

    def ingest(
        self,
        payload: Union[HomeAssistantPayload, Dict[str, Any]],
    ) -> StandardizedEnergyContext:
        """
        Executes end-to-end data ingestion:
        1. Merges stored WebUI configurations (battery, loads, thresholds) if omitted in payload
        2. Parsing raw payloads into DataFrames and models
        3. Validating, cleaning, and imputing values
        4. Normalizing time grids and computing energy features
        5. Tracking deferrable load power consumption and decomposing whole-house load
        """
        all_warnings: List[str] = []

        # Coerce payload model for flag inspection
        if isinstance(payload, dict):
            payload_model = HomeAssistantPayload.model_validate(payload)
        else:
            payload_model = payload

        # Merge stored configuration defaults from WebUI / config_store
        stored_cfg = config_store.config

        # 1. Parse Payload
        raw_df, battery, deferrable_loads, parse_warnings, actual_sensors = PayloadParser.parse(payload_model)
        all_warnings.extend(parse_warnings)

        # Fallback to stored battery configuration if not sent in payload
        if battery is None and stored_cfg.battery is not None:
            battery = stored_cfg.battery.model_copy()
            # If payload had a flat battery_soc, update it on the stored battery
            if payload_model.battery_soc is not None:
                battery.soc_percent = payload_model.battery_soc

        # Fallback to stored deferrable loads if empty in payload
        if (not deferrable_loads or len(deferrable_loads) == 0) and stored_cfg.deferrable_loads:
            deferrable_loads = [l.model_copy() for l in stored_cfg.deferrable_loads]

        # 2. Validate and Clean
        cleaned_df, val_warnings = DataValidator.validate_and_clean(
            df=raw_df,
            battery=battery,
            deferrable_loads=deferrable_loads,
            min_horizon_hours=self.min_horizon_hours,
            max_horizon_hours=self.max_horizon_hours,
        )
        all_warnings.extend(val_warnings)

        # Target timestep: only resample if explicitly passed in payload
        target_timestep = payload_model.target_timestep_minutes

        # 3. Normalize & Align Time Series
        processed_ts, norm_warnings = TimeSeriesNormalizer.normalize(
            df=cleaned_df,
            target_timestep_minutes=target_timestep,
            default_timestep_minutes=self.default_timestep_minutes,
        )
        all_warnings.extend(norm_warnings)

        # 4. Deferrable Load Consumption Tracking & House Power Decomposition
        active_deferrable_power = sum(
            load.active_power_w for load in deferrable_loads if load.is_included_in_total_load
        )
        active_breakdown = {
            load.id: load.active_power_w
            for load in deferrable_loads
            if load.active_power_w > 0
        }

        actual_house_power = actual_sensors.get("load_power_w")
        actual_baseline_load: Optional[float] = None

        deduct_enabled = (
            payload_model.deduct_deferrable_loads_from_house_power
            if payload_model.deduct_deferrable_loads_from_house_power is not None
            else stored_cfg.deduct_deferrable_loads_from_house_power
        )

        if actual_house_power is not None:
            actual_sensors["total_house_power_w"] = actual_house_power
            actual_sensors["deferrable_load_power_w"] = active_deferrable_power

            if deduct_enabled:
                actual_baseline_load = max(0.0, float(actual_house_power) - active_deferrable_power)
                actual_sensors["baseline_load_power_w"] = actual_baseline_load
                if active_deferrable_power > 0:
                    loads_str = ", ".join(f"{k}: {v:.0f}W" for k, v in active_breakdown.items())
                    all_warnings.append(
                        f"Deducted {active_deferrable_power:.1f} W of active deferrable load(s) ({loads_str}) "
                        f"from house_power ({actual_house_power:.1f} W), yielding pure baseline load of {actual_baseline_load:.1f} W."
                    )
            else:
                actual_baseline_load = float(actual_house_power)
                actual_sensors["baseline_load_power_w"] = actual_baseline_load

        # Arbitrage settings fallback
        export_arbitrage_enabled = (
            payload_model.enable_export_arbitrage
            if payload_model.enable_export_arbitrage is not None
            else stored_cfg.enable_export_arbitrage
        )
        min_profit = (
            payload_model.min_arbitrage_profit_per_kwh
            if payload_model.min_arbitrage_profit_per_kwh is not None
            else stored_cfg.min_arbitrage_profit_per_kwh
        )
        deg_cost = (
            payload_model.battery_degradation_cost_per_kwh
            if payload_model.battery_degradation_cost_per_kwh is not None
            else stored_cfg.battery_degradation_cost_per_kwh
        )
        max_export = (
            payload_model.max_grid_export_power_w
            if payload_model.max_grid_export_power_w is not None
            else stored_cfg.max_grid_export_power_w
        )

        # Construct Context
        context = StandardizedEnergyContext(
            time_series=processed_ts,
            battery=battery,
            deferrable_loads=deferrable_loads,
            timestep_minutes=processed_ts.timestep_minutes,
            horizon_hours=processed_ts.horizon_hours,
            actual_sensors=actual_sensors,
            active_deferrable_power_w=active_deferrable_power,
            actual_baseline_load_w=actual_baseline_load,
            warnings=all_warnings,
            metadata={
                "ingestion_status": "success",
                "raw_steps": len(raw_df),
                "normalized_steps": processed_ts.total_steps,
                "active_deferrable_loads_breakdown": active_breakdown,
                "deduct_deferrable_loads_enabled": deduct_enabled,
                "enable_export_arbitrage": export_arbitrage_enabled,
                "min_arbitrage_profit_per_kwh": min_profit,
                "battery_degradation_cost_per_kwh": deg_cost,
                "max_grid_export_power_w": max_export,
            },
        )

        return context
