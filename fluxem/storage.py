import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Field

from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad
from fluxem.models.response import OptimizationScheduleResponse
from fluxem.models.telemetry import (
    DashboardDataResponse,
    PlanAdherenceMetrics,
    TimestepActual,
)

logger = logging.getLogger("fluxem.storage")

DEFAULT_CONFIG_PATH = Path(os.environ.get("FLUXEM_CONFIG_PATH", os.environ.get("CONFIG_PATH", "data/config.json")))
DEFAULT_TELEMETRY_PATH = Path(os.environ.get("FLUXEM_TELEMETRY_PATH", os.environ.get("TELEMETRY_PATH", "data/telemetry.json")))


class AppConfigData(BaseModel):
    """Full user-configurable application configuration schema."""
    # General & Engine settings
    default_timestep_minutes: int = Field(default=30, ge=1, le=120)
    prediction_horizon_days: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Lookahead optimization horizon in days (1 to 3 days / 24h to 72h)",
    )
    min_horizon_hours: float = Field(default=2.0, ge=1.0)
    max_horizon_hours: float = Field(default=72.0, le=168.0)
    default_currency: str = Field(default="$")

    # Historical Load Forecasting (from Home Assistant Sensor History)
    load_history_days: int = Field(
        default=3,
        ge=1,
        le=14,
        description="Number of past days history to analyze for household load forecasting (1 to 14 days)",
    )
    load_forecast_method: str = Field(
        default="moving_average",
        description="Method to predict baseline load from historical data: moving_average, median_profile, same_day_last_week",
    )

    # Direct Home Assistant API Integration
    ha_url: Optional[str] = Field(default="http://homeassistant.local:8123", description="Home Assistant base URL")
    ha_token: Optional[str] = Field(default=None, description="Home Assistant Long-Lived Access Token")
    ha_timezone: str = Field(default="auto", description="Home Assistant timezone (e.g. Australia/Sydney, America/New_York, or auto)")
    ha_entity_mappings: Dict[str, str] = Field(
        default_factory=lambda: {
            "solar_forecast_entity": "sensor.solcast_pv_forecast",
            "buy_price_forecast_entity": "sensor.amber_general_forecast",
            "sell_price_forecast_entity": "sensor.amber_feed_in_forecast",
            "house_power_entity": "sensor.power_meter_house",
            "battery_soc_entity": "sensor.battery_state_of_charge",
        },
        description="Mappings of FluxEM roles to Home Assistant entity IDs",
    )

    # MQTT Settings
    mqtt_enabled: bool = Field(default=False)
    mqtt_broker_host: str = Field(default="localhost")
    mqtt_broker_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: Optional[str] = Field(default=None)
    mqtt_password: Optional[str] = Field(default=None)
    mqtt_topic_prefix: str = Field(default="fluxem")

    # Battery Defaults
    battery: Optional[BatteryState] = Field(default=None)

    # Deferrable Loads List
    deferrable_loads: List[DeferrableLoad] = Field(default_factory=list)

    # Export Arbitrage (Module C)
    enable_export_arbitrage: bool = Field(default=False)
    min_arbitrage_profit_per_kwh: float = Field(default=0.03, ge=0.0)
    battery_degradation_cost_per_kwh: float = Field(default=0.01, ge=0.0)
    max_grid_export_power_w: Optional[float] = Field(default=None)

    # Drift Watchdog (Module D)
    solar_drift_threshold_pct: float = Field(default=25.0, ge=1.0, le=100.0)
    price_drift_threshold_pct: float = Field(default=20.0, ge=1.0, le=100.0)
    load_drift_threshold_pct: float = Field(default=30.0, ge=1.0, le=100.0)
    soc_drift_threshold_pct: float = Field(default=10.0, ge=1.0, le=50.0)

    # Deferrable load deduction default
    deduct_deferrable_loads_from_house_power: bool = Field(default=True)


class ConfigStore:
    """
    Manages loading, updating, and saving configuration to disk.
    """

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self._config: AppConfigData = AppConfigData()
        self.load()

    @property
    def config(self) -> AppConfigData:
        return self._config

    def load(self) -> AppConfigData:
        """Loads configuration from persistent JSON file on disk, or initializes defaults."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = AppConfigData.model_validate(data)
                logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to parse configuration file {self.config_path}: {e}. Using defaults.")
                self._config = AppConfigData()
        else:
            logger.info(f"No configuration file found at {self.config_path}. Initializing defaults.")
            self._config = AppConfigData()
            self.save(self._config)

        return self._config

    def save(self, new_config: AppConfigData) -> bool:
        """Saves configuration data to persistent JSON file on disk."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(new_config.model_dump(), f, indent=2)
            self._config = new_config
            logger.info(f"Saved configuration to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration to {self.config_path}: {e}")
            return False

    def update_from_dict(self, data: Dict[str, Any]) -> AppConfigData:
        """Validates and updates configuration from dictionary, merging with existing config."""
        current_dict = self._config.model_dump()
        for k, v in data.items():
            current_dict[k] = v
        validated = AppConfigData.model_validate(current_dict)
        self.save(validated)
        return self._config


class TelemetryStore:
    """
    Manages persistent storage of today's Baseline Plan of Record,
    interval-by-interval realized sensor actuals, and adherence calculation.
    """

    def __init__(self, telemetry_path: Path = DEFAULT_TELEMETRY_PATH):
        self.telemetry_path = telemetry_path
        self._today_date: str = ""
        self._timezone_name: str = "UTC"
        self._baseline_plan: Optional[OptimizationScheduleResponse] = None
        self._baseline_locked: bool = False
        self._baseline_established_at: Optional[str] = None
        self._active_schedule: Optional[OptimizationScheduleResponse] = None
        self._actuals: Dict[str, TimestepActual] = {}
        self.load()

    def _get_local_tz(self, tz_name: Optional[str] = None) -> ZoneInfo:
        effective = tz_name or self._timezone_name or "UTC"
        if effective.lower() in ("auto", "none", ""):
            effective = "UTC"
        try:
            return ZoneInfo(effective)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _get_current_local_date_str(self, tz_name: Optional[str] = None) -> str:
        tz = self._get_local_tz(tz_name)
        return datetime.now(tz).strftime("%Y-%m-%d")

    def check_day_rollover(self, tz_name: Optional[str] = None) -> bool:
        """Checks if local date has rolled over to a new day. Resets daily buffer if changed."""
        cur_date = self._get_current_local_date_str(tz_name)
        if self._today_date != cur_date:
            logger.info(f"Day rollover detected: {self._today_date} -> {cur_date}. Resetting daily telemetry buffer.")
            self._today_date = cur_date
            self._actuals.clear()
            self._baseline_plan = None
            self._baseline_locked = False
            self._baseline_established_at = None
            self._active_schedule = None
            self.save()
            return True
        return False

    def load(self):
        """Loads telemetry buffer from disk if available."""
        if self.telemetry_path.exists():
            try:
                with open(self.telemetry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._today_date = data.get("today_date", "")
                self._timezone_name = data.get("timezone", "UTC")
                self._baseline_locked = data.get("baseline_locked", False)
                self._baseline_established_at = data.get("baseline_established_at")

                if data.get("baseline_plan"):
                    self._baseline_plan = OptimizationScheduleResponse.model_validate(data["baseline_plan"])
                if data.get("active_schedule"):
                    self._active_schedule = OptimizationScheduleResponse.model_validate(data["active_schedule"])

                actuals_raw = data.get("actuals", {})
                self._actuals = {
                    ts: TimestepActual.model_validate(item) for ts, item in actuals_raw.items()
                }
                logger.info(f"Loaded telemetry buffer for {self._today_date} ({len(self._actuals)} records)")
            except Exception as e:
                logger.warning(f"Could not load telemetry buffer from {self.telemetry_path}: {e}")
                self._today_date = self._get_current_local_date_str()
                self._actuals.clear()
        else:
            self._today_date = self._get_current_local_date_str()

    def save(self) -> bool:
        """Persists telemetry buffer to disk."""
        try:
            self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "today_date": self._today_date,
                "timezone": self._timezone_name,
                "baseline_locked": self._baseline_locked,
                "baseline_established_at": self._baseline_established_at,
                "baseline_plan": self._baseline_plan.model_dump() if self._baseline_plan else None,
                "active_schedule": self._active_schedule.model_dump() if self._active_schedule else None,
                "actuals": {ts: act.model_dump() for ts, act in self._actuals.items()},
            }
            with open(self.telemetry_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save telemetry buffer to {self.telemetry_path}: {e}")
            return False

    def record_actual(
        self,
        timestamp: str,
        solar_power_w: Optional[float] = None,
        house_power_w: Optional[float] = None,
        baseline_load_w: Optional[float] = None,
        battery_soc_percent: Optional[float] = None,
        battery_power_w: Optional[float] = None,
        deferrable_load_power_w: Optional[Dict[str, float]] = None,
        buy_price: Optional[float] = None,
        sell_price: Optional[float] = None,
        grid_import_power_w: Optional[float] = None,
        grid_export_power_w: Optional[float] = None,
        tz_name: Optional[str] = None,
    ):
        """Records an actual realized sensor telemetry point for a given interval timestamp."""
        self.check_day_rollover(tz_name)
        existing = self._actuals.get(timestamp)
        if existing:
            if solar_power_w is not None: existing.solar_power_w = round(solar_power_w, 1)
            if house_power_w is not None: existing.house_power_w = round(house_power_w, 1)
            if baseline_load_w is not None: existing.baseline_load_w = round(baseline_load_w, 1)
            if battery_soc_percent is not None: existing.battery_soc_percent = round(battery_soc_percent, 1)
            if battery_power_w is not None: existing.battery_power_w = round(battery_power_w, 1)
            if deferrable_load_power_w: existing.deferrable_load_power_w.update(deferrable_load_power_w)
            if buy_price is not None: existing.buy_price = round(buy_price, 4)
            if sell_price is not None: existing.sell_price = round(sell_price, 4)
            if grid_import_power_w is not None: existing.grid_import_power_w = round(grid_import_power_w, 1)
            if grid_export_power_w is not None: existing.grid_export_power_w = round(grid_export_power_w, 1)
        else:
            self._actuals[timestamp] = TimestepActual(
                timestamp=timestamp,
                solar_power_w=round(solar_power_w, 1) if solar_power_w is not None else None,
                house_power_w=round(house_power_w, 1) if house_power_w is not None else None,
                baseline_load_w=round(baseline_load_w, 1) if baseline_load_w is not None else None,
                battery_soc_percent=round(battery_soc_percent, 1) if battery_soc_percent is not None else None,
                battery_power_w=round(battery_power_w, 1) if battery_power_w is not None else None,
                deferrable_load_power_w=deferrable_load_power_w or {},
                buy_price=round(buy_price, 4) if buy_price is not None else None,
                sell_price=round(sell_price, 4) if sell_price is not None else None,
                grid_import_power_w=round(grid_import_power_w, 1) if grid_import_power_w is not None else None,
                grid_export_power_w=round(grid_export_power_w, 1) if grid_export_power_w is not None else None,
            )
        self.save()

    def record_actuals_batch(self, batch: Dict[str, TimestepActual], tz_name: Optional[str] = None):
        """Records multiple actual telemetry records (e.g. from Home Assistant history)."""
        self.check_day_rollover(tz_name)
        for ts, act in batch.items():
            self._actuals[ts] = act
        self.save()

    def set_baseline_plan(
        self,
        plan: OptimizationScheduleResponse,
        lock: bool = False,
        tz_name: Optional[str] = None,
    ):
        """Sets today's baseline Plan of Record."""
        self.check_day_rollover(tz_name)
        self._baseline_plan = plan
        self._baseline_locked = lock
        self._baseline_established_at = datetime.now(timezone.utc).isoformat()
        self.save()
        logger.info(f"Baseline Plan of Record set (Locked={lock}, Timestamps={len(plan.timestamps)})")

    def lock_baseline_plan(self):
        """Explicitly locks the baseline plan so subsequent runs won't overwrite it."""
        if not self._baseline_plan and self._active_schedule:
            self._baseline_plan = self._active_schedule
        self._baseline_locked = True
        self._baseline_established_at = datetime.now(timezone.utc).isoformat()
        self.save()
        logger.info("Baseline plan explicitly locked by user.")

    def reset_baseline_plan(self):
        """Resets today's baseline plan allowing a fresh one to be established."""
        self._baseline_plan = None
        self._baseline_locked = False
        self._baseline_established_at = None
        self.save()
        logger.info("Baseline plan reset.")

    def set_active_schedule(self, plan: OptimizationScheduleResponse, tz_name: Optional[str] = None):
        """Updates the active schedule from the latest optimization run."""
        self.check_day_rollover(tz_name)
        self._active_schedule = plan
        if self._baseline_plan is None and not self._baseline_locked:
            # Auto-establish first optimization of the day as Baseline Plan of Record
            self.set_baseline_plan(plan, lock=False, tz_name=tz_name)
        else:
            self.save()

    def calculate_adherence(
        self,
        baseline: Optional[OptimizationScheduleResponse],
        actuals: Dict[str, TimestepActual],
        tz_name: str = "UTC",
    ) -> PlanAdherenceMetrics:
        """Calculates statistical adherence metrics comparing Plan of Record against Realized Actuals."""
        metrics = PlanAdherenceMetrics()
        metrics.is_baseline_locked = self._baseline_locked
        metrics.baseline_established_at = self._baseline_established_at

        if not baseline or not baseline.timestamps:
            metrics.has_baseline_plan = False
            return metrics

        metrics.has_baseline_plan = True

        # Calculate timestep duration
        timestep_minutes = 30
        if len(baseline.timestamps) >= 2:
            try:
                t0 = datetime.fromisoformat(baseline.timestamps[0].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(baseline.timestamps[1].replace("Z", "+00:00"))
                timestep_minutes = int((t1 - t0).total_seconds() // 60)
            except Exception:
                timestep_minutes = 30
        dt_hours = timestep_minutes / 60.0

        now_utc = datetime.now(timezone.utc)
        elapsed_steps = 0
        cur_idx = 0
        latest_ts = ""

        # Limit full-day planned accumulation to first 24h (e.g. 48 steps for 30m)
        steps_in_day = min(len(baseline.timestamps), 1440 // timestep_minutes)
        for i in range(steps_in_day):
            metrics.full_day_planned_solar_kwh += (baseline.solar_forecast_w[i] or 0.0) * dt_hours / 1000.0
            metrics.full_day_planned_load_kwh += (baseline.baseline_load_w[i] or 0.0) * dt_hours / 1000.0

        metrics.full_day_planned_solar_kwh = round(metrics.full_day_planned_solar_kwh, 2)
        metrics.full_day_planned_load_kwh = round(metrics.full_day_planned_load_kwh, 2)

        for idx, ts in enumerate(baseline.timestamps):
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts_dt = now_utc

            # Step has elapsed or is current
            if ts_dt <= now_utc:
                elapsed_steps += 1
                cur_idx = idx
                latest_ts = ts

                p_solar = baseline.solar_forecast_w[idx] if idx < len(baseline.solar_forecast_w) else 0.0
                p_load = baseline.baseline_load_w[idx] if idx < len(baseline.baseline_load_w) else 0.0
                metrics.planned_solar_kwh += p_solar * dt_hours / 1000.0
                metrics.planned_load_kwh += p_load * dt_hours / 1000.0

                if ts in actuals:
                    act = actuals[ts]
                    if act.solar_power_w is not None:
                        metrics.actual_solar_kwh += act.solar_power_w * dt_hours / 1000.0
                    if act.baseline_load_w is not None:
                        metrics.actual_load_kwh += act.baseline_load_w * dt_hours / 1000.0
                    elif act.house_power_w is not None:
                        metrics.actual_load_kwh += act.house_power_w * dt_hours / 1000.0

                    if act.battery_soc_percent is not None:
                        metrics.actual_battery_soc = act.battery_soc_percent

                if baseline.battery_soc_percent and idx < len(baseline.battery_soc_percent):
                    metrics.planned_battery_soc = baseline.battery_soc_percent[idx]

        metrics.elapsed_steps = elapsed_steps
        metrics.current_step_index = cur_idx
        metrics.current_timestamp = latest_ts
        metrics.actual_solar_kwh = round(metrics.actual_solar_kwh, 2)
        metrics.planned_solar_kwh = round(metrics.planned_solar_kwh, 2)
        metrics.actual_load_kwh = round(metrics.actual_load_kwh, 2)
        metrics.planned_load_kwh = round(metrics.planned_load_kwh, 2)

        metrics.solar_delta_kwh = round(metrics.actual_solar_kwh - metrics.planned_solar_kwh, 2)
        denom_solar = max(metrics.planned_solar_kwh, 0.2)
        metrics.solar_drift_pct = round(((metrics.actual_solar_kwh - metrics.planned_solar_kwh) / denom_solar) * 100.0, 1)

        metrics.load_delta_kwh = round(metrics.actual_load_kwh - metrics.planned_load_kwh, 2)
        denom_load = max(metrics.planned_load_kwh, 0.2)
        metrics.load_drift_pct = round(((metrics.actual_load_kwh - metrics.planned_load_kwh) / denom_load) * 100.0, 1)

        if metrics.actual_battery_soc is not None and metrics.planned_battery_soc is not None:
            metrics.battery_soc_delta = round(metrics.actual_battery_soc - metrics.planned_battery_soc, 1)

        return metrics

    def get_dashboard_data(
        self,
        ha_timezone: str = "UTC",
        horizon_days: int = 1,
        watchdog_status: str = "nominal",
        watchdog_reason: str = "",
    ) -> DashboardDataResponse:
        """Constructs the comprehensive dashboard dataset for the UI."""
        self.check_day_rollover(ha_timezone)
        tz_obj = self._get_local_tz(ha_timezone)
        now_local = datetime.now(tz_obj)

        adherence = self.calculate_adherence(
            baseline=self._baseline_plan or self._active_schedule,
            actuals=self._actuals,
            tz_name=ha_timezone,
        )
        adherence.watchdog_status = watchdog_status
        adherence.watchdog_reason = watchdog_reason

        return DashboardDataResponse(
            timezone=str(tz_obj),
            current_time=now_local.isoformat(),
            today_date=self._today_date or now_local.strftime("%Y-%m-%d"),
            horizon_days=horizon_days,
            current_step_index=adherence.current_step_index,
            is_today_window=True,
            baseline_plan=self._baseline_plan,
            active_schedule=self._active_schedule or self._baseline_plan,
            actuals=self._actuals,
            adherence=adherence,
            config_summary=config_store.config.model_dump(),
        )


config_store = ConfigStore()
telemetry_store = TelemetryStore()
