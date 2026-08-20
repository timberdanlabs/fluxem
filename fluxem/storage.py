"""
Persistent storage manager for FluxEM WebUI configuration.
Saves and loads user-configured battery specs, deferrable loads, thresholds, and MQTT/HA settings.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad

logger = logging.getLogger("fluxem.storage")

DEFAULT_CONFIG_PATH = Path("data/config.json")


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
        """Validates and updates configuration from dictionary."""
        validated = AppConfigData.model_validate(data)
        self.save(validated)
        return self._config


config_store = ConfigStore()
