"""
Home Assistant incoming payload schemas and validation models.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator

from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad


class TimeSeriesStep(BaseModel):
    """Single time-step forecast entry when passed as a structured record."""
    timestamp: Union[datetime, str] = Field(..., description="Timestamp of the interval")
    buy_price: Optional[float] = Field(None, description="Electricity import/buy price ($/kWh)")
    sell_price: Optional[float] = Field(default=0.0, description="Electricity export/feed-in price ($/kWh)")
    solar_power: Optional[float] = Field(default=0.0, ge=0.0, description="Forecasted solar generation (W)")
    load_power: Optional[float] = Field(default=0.0, ge=0.0, description="Forecasted baseline home load (W)")


class HomeAssistantPayload(BaseModel):
    """
    Unified payload model accepting Home Assistant data in either flat array format
    or structured record format, with flexible sensor aliases.
    """
    # Flat array inputs (allows None/NaN within arrays for imputation)
    timestamps: Optional[List[Union[datetime, str]]] = Field(
        default=None,
        description="List of ISO-8601 timestamps defining each forecast horizon interval",
        examples=[["2026-08-20T00:00:00Z", "2026-08-20T00:30:00Z"]],
    )
    buy_prices: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Array of grid import / buy electricity prices per kWh",
        examples=[[0.24, 0.22, 0.18]],
    )
    sell_prices: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Array of grid export / feed-in tariff prices per kWh",
        examples=[[0.08, 0.08, 0.06]],
    )
    solar_forecast: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Array of forecasted PV solar generation values (Watts or kW)",
        examples=[[0.0, 500.0, 3200.0]],
    )
    load_forecast: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Array of forecasted baseline household consumption values (Watts or kW)",
        examples=[[450.0, 600.0, 550.0]],
    )

    # Structured time series alternative
    time_series: Optional[List[TimeSeriesStep]] = Field(
        default=None,
        description="Alternative structured list of forecast step objects",
    )

    # Battery definitions: either nested BatteryState or flat convenience fields
    battery: Optional[BatteryState] = Field(
        default=None,
        description="Battery storage parameters and state",
    )
    battery_soc: Optional[float] = Field(default=None, description="Current Battery SOC % (flat shortcut)")
    battery_capacity_kwh: Optional[float] = Field(default=None, description="Battery capacity in kWh (flat shortcut)")
    battery_max_charge_power_w: Optional[float] = Field(default=None, description="Max charge power in Watts (flat shortcut)")
    battery_max_discharge_power_w: Optional[float] = Field(default=None, description="Max discharge power in Watts (flat shortcut)")
    battery_min_soc: Optional[float] = Field(default=None, description="Min SOC % (flat shortcut)")
    battery_max_soc: Optional[float] = Field(default=None, description="Max SOC % (flat shortcut)")
    battery_efficiency: Optional[float] = Field(default=None, description="Round trip efficiency (flat shortcut)")
    battery_current_power_w: Optional[float] = Field(default=None, description="Current battery power (flat shortcut)")

    # Deferrable loads
    deferrable_loads: Optional[List[DeferrableLoad]] = Field(
        default_factory=list,
        description="List of deferrable controllable loads and run requirements",
    )

    # Real-time observed sensor values for Watchdog Drift analysis & load decomposition
    actual_solar_power_w: Optional[float] = Field(
        default=None,
        description="Actual real-time observed solar power in Watts for drift watchdog",
    )
    actual_load_power_w: Optional[float] = Field(
        default=None,
        description="Actual real-time observed whole-home load / house_power in Watts",
    )
    actual_buy_price: Optional[float] = Field(
        default=None,
        description="Actual current spot buy price for drift watchdog",
    )
    actual_sell_price: Optional[float] = Field(
        default=None,
        description="Actual current spot sell price for drift watchdog",
    )

    # Automatic deferrable load deduction from whole home consumption
    deduct_deferrable_loads_from_house_power: bool = Field(
        default=True,
        description=(
            "If True, automatically deducts active deferrable load consumption (current_power_w / active running state) "
            "from whole-house power sensor (actual_load_power_w) so users don't need custom Home Assistant template sensors."
        ),
    )

    # Battery Arbitrage & Grid Export Controls (Module C)
    enable_export_arbitrage: Optional[bool] = Field(
        default=None,
        description="If True, enables dynamic grid-charge to feed-in export arbitrage when future export prices exceed current buy prices + margin",
    )
    min_arbitrage_profit_per_kwh: Optional[float] = Field(
        default=None,
        description="Custom profit hurdle rate ($/kWh) required to trigger export arbitrage",
    )
    battery_degradation_cost_per_kwh: Optional[float] = Field(
        default=None,
        description="Custom battery cycling wear cost ($/kWh)",
    )
    max_grid_export_power_w: Optional[float] = Field(
        default=None,
        description="Inverter or DNO grid export power limit in Watts",
    )

    # Configuration & unit hints
    unit_load: Optional[str] = Field(
        default="W",
        description="Unit for load forecast: 'W' (Watts) or 'kW' (Kilowatts)",
    )
    unit_solar: Optional[str] = Field(
        default="W",
        description="Unit for solar forecast: 'W' (Watts) or 'kW' (Kilowatts)",
    )
    unit_price: Optional[str] = Field(
        default="$/kWh",
        description="Unit for price forecast: '$/kWh' or 'c/kWh' (cents)",
    )
    target_timestep_minutes: Optional[int] = Field(
        default=None,
        description="Target uniform timestep interval in minutes for re-sampling (e.g. 5, 15, 30, 60)",
    )
    prediction_horizon_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=3,
        description="Lookahead horizon in days (1 to 3 days)",
    )
    load_history_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=14,
        description="Number of past days history to analyze for load forecasting (1 to 14 days)",
    )
    ha_timezone: Optional[str] = Field(
        default=None,
        description="Timezone of the Home Assistant instance (e.g. 'Australia/Sydney', 'America/New_York')",
        examples=["Australia/Sydney"],
    )
    force_reoptimize: bool = Field(
        default=False,
        description="If True, forces full re-optimization ignoring Drift Watchdog thresholds",
    )
    extra_attributes: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Any extra custom attributes from Home Assistant",
    )

    @model_validator(mode="before")
    @classmethod
    def extract_aliases_and_flat_structures(cls, data: Any) -> Any:
        """
        Handle flexible Home Assistant template aliases (e.g., Solcast, Amber, Tibber names).
        Distinguishes array time-series vs single-value real-time sensors.
        """
        if not isinstance(data, dict):
            return data

        # Extract timezone aliases
        if "ha_timezone" not in data or data.get("ha_timezone") is None:
            for tz_alias in ["timezone", "time_zone", "ha_tz"]:
                if tz_alias in data and data[tz_alias]:
                    data["ha_timezone"] = str(data[tz_alias])
                    break

        # Array mappings (must be list/tuple)
        array_mappings = {
            "buy_prices": [
                "buy_prices", "price_buy", "import_prices", "import_price_forecast",
                "pricing_buy", "buy_price_forecast", "grid_buy_prices", "prices_buy",
            ],
            "sell_prices": [
                "sell_prices", "price_sell", "export_prices", "export_price_forecast",
                "pricing_sell", "sell_price_forecast", "feedin_prices", "prices_sell",
                "feed_in_tariff", "feedin_tariff",
            ],
            "solar_forecast": [
                "solar_forecast", "pv_forecast", "solar_power_forecast", "pv_power_forecast",
                "solar_forecast_watts", "solcast_pv_forecast", "pv_power",
            ],
            "load_forecast": [
                "load_forecast", "home_load_forecast", "baseline_load_forecast",
                "load_power_forecast", "home_load", "load_forecast_watts",
                "house_power", "house_load",
            ],
            "timestamps": [
                "timestamps", "time_stamps", "dates", "interval_starts", "timestamp_array",
            ],
            "deferrable_loads": [
                "deferrable_loads", "loads", "deferrable_load_list", "controllable_loads",
            ],
        }

        for canonical_name, aliases in array_mappings.items():
            if canonical_name not in data or data[canonical_name] is None:
                for alias in aliases:
                    if alias in data and data[alias] is not None and isinstance(data[alias], (list, tuple)):
                        data[canonical_name] = data[alias]
                        break

        # Scalar mappings (must NOT be list/tuple)
        scalar_mappings = {
            "actual_load_power_w": [
                "actual_load_power_w", "house_power", "home_power", "current_house_power",
                "current_load_power", "house_consumption", "home_consumption",
                "whole_house_power", "current_house_consumption",
            ],
            "actual_solar_power_w": [
                "actual_solar_power_w", "current_solar_power", "pv_power_now",
                "current_pv_power", "solar_power_now", "pv_now",
            ],
            "actual_buy_price": [
                "actual_buy_price", "current_buy_price", "current_spot_price",
                "spot_price_now", "current_price_buy",
            ],
            "actual_sell_price": [
                "actual_sell_price", "current_sell_price", "current_feedin_price",
                "current_price_sell", "feedin_price_now",
            ],
            "enable_export_arbitrage": [
                "enable_export_arbitrage", "export_arbitrage_enabled", "arbitrage_enabled",
                "enable_arbitrage", "feedin_arbitrage",
            ],
        }

        for canonical_name, aliases in scalar_mappings.items():
            if canonical_name not in data or data[canonical_name] is None:
                for alias in aliases:
                    if alias in data and data[alias] is not None and not isinstance(data[alias], (list, tuple, dict)):
                        data[canonical_name] = data[alias]
                        break

        # Map flat battery fields into BatteryState if battery object not explicitly provided
        if ("battery" not in data or data["battery"] is None) and (
            data.get("battery_soc") is not None and data.get("battery_capacity_kwh") is not None
        ):
            battery_dict: Dict[str, Any] = {
                "soc_percent": data.get("battery_soc"),
                "capacity_kwh": data.get("battery_capacity_kwh"),
            }
            if data.get("battery_max_charge_power_w") is not None:
                battery_dict["max_charge_power_w"] = data.get("battery_max_charge_power_w")
            if data.get("battery_max_discharge_power_w") is not None:
                battery_dict["max_discharge_power_w"] = data.get("battery_max_discharge_power_w")
            if data.get("battery_min_soc") is not None:
                battery_dict["min_soc_percent"] = data.get("battery_min_soc")
            if data.get("battery_max_soc") is not None:
                battery_dict["max_soc_percent"] = data.get("battery_max_soc")
            if data.get("battery_efficiency") is not None:
                battery_dict["round_trip_efficiency"] = data.get("battery_efficiency")
            if data.get("battery_current_power_w") is not None:
                battery_dict["current_power_w"] = data.get("battery_current_power_w")

            data["battery"] = battery_dict

        return data
