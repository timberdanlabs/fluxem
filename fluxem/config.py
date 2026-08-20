"""
Configuration management for FluxEM microservice using Pydantic Settings.
"""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Server settings
    host: str = Field(default="0.0.0.0", description="Host to bind HTTP server")
    port: int = Field(default=8000, description="Port to bind HTTP server")
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")
    app_name: str = Field(default="FluxEM", description="Application name")
    environment: str = Field(default="production", description="Runtime environment (development, test, production)")

    # Time-series and optimization defaults
    default_timestep_minutes: int = Field(
        default=30,
        description="Default interval length in minutes when unspecified (5, 15, 30, 60)",
    )
    prediction_horizon_days: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Lookahead optimization horizon in days (1 to 3 days)",
    )
    max_horizon_hours: int = Field(default=72, description="Maximum forecast horizon to accept in hours (up to 3 days)")
    min_horizon_hours: int = Field(default=2, description="Minimum forecast horizon required in hours")
    default_currency: str = Field(default="$", description="Default currency symbol for logs and reports")

    # Historical Load Forecasting settings
    load_history_days: int = Field(
        default=3,
        ge=1,
        le=14,
        description="Number of historical days analyzed from Home Assistant to forecast home load (1 to 14 days)",
    )
    load_forecast_method: str = Field(
        default="moving_average",
        description="Method to predict baseline load from historical data: moving_average, median_profile, same_day_last_week",
    )

    # Battery Arbitrage & Export Mode (Module C)
    enable_export_arbitrage: bool = Field(
        default=False,
        description="Optional mode: charge from grid during cheap hours to export during future high feed-in price spikes",
    )
    min_arbitrage_profit_per_kwh: float = Field(
        default=0.03,
        description="Minimum net profit margin ($/kWh) after round-trip efficiency and cycle degradation to execute export arbitrage",
    )
    battery_degradation_cost_per_kwh: float = Field(
        default=0.01,
        description="Estimated battery wear/cycling cost per throughput kWh ($/kWh)",
    )
    max_grid_export_power_w: Optional[float] = Field(
        default=None,
        description="Maximum permitted grid export power in Watts (e.g., DNO/inverter export limit)",
    )

    # MQTT Settings
    mqtt_enabled: bool = Field(default=False, description="Enable MQTT publishing")
    mqtt_broker_host: str = Field(default="localhost", description="MQTT broker hostname or IP")
    mqtt_broker_port: int = Field(default=1883, description="MQTT broker port")
    mqtt_username: Optional[str] = Field(default=None, description="MQTT username")
    mqtt_password: Optional[str] = Field(default=None, description="MQTT password")
    mqtt_topic_prefix: str = Field(default="fluxem", description="Prefix for published MQTT topics")
    mqtt_keepalive: int = Field(default=60, description="MQTT keepalive interval in seconds")

    # Drift Watchdog Thresholds (Module D)
    solar_drift_threshold_pct: float = Field(
        default=25.0,
        description="Variance threshold (%) in solar generation to trigger re-optimization",
    )
    price_drift_threshold_pct: float = Field(
        default=20.0,
        description="Variance threshold (%) in buy/sell price to trigger re-optimization",
    )
    load_drift_threshold_pct: float = Field(
        default=30.0,
        description="Variance threshold (%) in baseline load to trigger re-optimization",
    )


settings = Settings()
