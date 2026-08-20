"""
Payload parser for Agnostic Data Ingestion.
Transforms arbitrary Home Assistant payload formats (flat lists, dicts, records)
into standard Pandas DataFrames and domain objects.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad
from fluxem.models.payload import HomeAssistantPayload, TimeSeriesStep


class PayloadParser:
    """
    Parses and sanitizes input data from Home Assistant into normalized internal structures.
    """

    @classmethod
    def parse(
        cls,
        payload: Union[HomeAssistantPayload, Dict[str, Any]],
    ) -> Tuple[pd.DataFrame, Optional[BatteryState], List[DeferrableLoad], List[str], Dict[str, Any]]:
        """
        Parses raw payload into:
        1. pd.DataFrame with raw time-series columns
        2. BatteryState (if provided)
        3. List of DeferrableLoad
        4. List of warning strings generated during parsing
        5. Actual sensor observations dictionary (for drift watchdog)
        """
        warnings: List[str] = []

        # Validate / coerce into HomeAssistantPayload if a raw dict was passed
        if isinstance(payload, dict):
            payload_model = HomeAssistantPayload.model_validate(payload)
        else:
            payload_model = payload

        # Extract actual sensor states
        actual_sensors = {
            "solar_power_w": payload_model.actual_solar_power_w,
            "load_power_w": payload_model.actual_load_power_w,
            "buy_price": payload_model.actual_buy_price,
            "sell_price": payload_model.actual_sell_price,
        }

        # Case 1: Structured TimeSeriesStep list provided
        if payload_model.time_series and len(payload_model.time_series) > 0:
            df, parse_warnings = cls._parse_structured_time_series(payload_model.time_series)
            warnings.extend(parse_warnings)
        # Case 2: Flat arrays provided
        elif payload_model.timestamps and len(payload_model.timestamps) > 0:
            df, parse_warnings = cls._parse_flat_arrays(payload_model)
            warnings.extend(parse_warnings)
        else:
            raise ValueError(
                "Payload must contain either 'timestamps' (with aligned price/load/solar arrays) "
                "or a 'time_series' list of step objects."
            )

        # Apply Unit Conversions
        df, unit_warnings = cls._apply_unit_conversions(
            df=df,
            unit_load=payload_model.unit_load or "W",
            unit_solar=payload_model.unit_solar or "W",
            unit_price=payload_model.unit_price or "$/kWh",
        )
        warnings.extend(unit_warnings)

        # Extract Deferrable Loads
        deferrable_loads = payload_model.deferrable_loads or []

        return df, payload_model.battery, deferrable_loads, warnings, actual_sensors

    @classmethod
    def _parse_structured_time_series(
        cls,
        steps: List[TimeSeriesStep],
    ) -> Tuple[pd.DataFrame, List[str]]:
        warnings: List[str] = []
        records = []
        for step in steps:
            records.append({
                "timestamp": step.timestamp,
                "buy_price": float(step.buy_price) if step.buy_price is not None else np.nan,
                "sell_price": float(step.sell_price) if step.sell_price is not None else np.nan,
                "solar_power_w": float(step.solar_power) if step.solar_power is not None else np.nan,
                "load_power_w": float(step.load_power) if step.load_power is not None else np.nan,
            })

        df = pd.DataFrame.from_records(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return df, warnings

    @classmethod
    def _parse_flat_arrays(
        cls,
        payload: HomeAssistantPayload,
    ) -> Tuple[pd.DataFrame, List[str]]:
        warnings: List[str] = []
        timestamps = payload.timestamps or []

        if payload.buy_prices is None or len(payload.buy_prices) == 0:
            raise ValueError("buy_prices array is required and cannot be empty.")

        n_ts = len(timestamps)
        n_buy = len(payload.buy_prices)

        # Determine target length (align to timestamps or shortest array)
        min_length = min(n_ts, n_buy)
        if payload.solar_forecast is not None and len(payload.solar_forecast) > 0:
            min_length = min(min_length, len(payload.solar_forecast))
        if payload.load_forecast is not None and len(payload.load_forecast) > 0:
            min_length = min(min_length, len(payload.load_forecast))
        if payload.sell_prices is not None and len(payload.sell_prices) > 0:
            min_length = min(min_length, len(payload.sell_prices))

        if min_length < n_ts:
            warnings.append(
                f"Array length mismatch detected (timestamps={n_ts}, buy_prices={n_buy}). "
                f"Truncating aligned arrays to common length {min_length}."
            )

        parsed_timestamps = pd.to_datetime(timestamps[:min_length], utc=True)

        buy_prices = [
            float(x) if x is not None and not np.isnan(float(x)) else np.nan
            for x in payload.buy_prices[:min_length]
        ]

        if payload.sell_prices is not None and len(payload.sell_prices) > 0:
            sell_prices = [
                float(x) if x is not None and not np.isnan(float(x)) else np.nan
                for x in payload.sell_prices[:min_length]
            ]
        else:
            warnings.append("sell_prices not provided; assuming feed-in tariff of 0.00 $/kWh.")
            sell_prices = [0.0] * min_length

        if payload.solar_forecast is not None and len(payload.solar_forecast) > 0:
            solar_power = [
                float(x) if x is not None and not np.isnan(float(x)) else np.nan
                for x in payload.solar_forecast[:min_length]
            ]
        else:
            warnings.append("solar_forecast not provided; assuming 0.0 W solar generation.")
            solar_power = [0.0] * min_length

        if payload.load_forecast is not None and len(payload.load_forecast) > 0:
            load_power = [
                float(x) if x is not None and not np.isnan(float(x)) else np.nan
                for x in payload.load_forecast[:min_length]
            ]
        else:
            warnings.append("load_forecast not provided; defaulting to baseline home load of 500.0 W.")
            load_power = [500.0] * min_length

        df = pd.DataFrame({
            "buy_price": buy_prices,
            "sell_price": sell_prices,
            "solar_power_w": solar_power,
            "load_power_w": load_power,
        }, index=parsed_timestamps)

        df.index.name = "timestamp"
        return df, warnings

    @classmethod
    def _apply_unit_conversions(
        cls,
        df: pd.DataFrame,
        unit_load: str,
        unit_solar: str,
        unit_price: str,
    ) -> Tuple[pd.DataFrame, List[str]]:
        warnings: List[str] = []
        df = df.copy()

        # Solar units (convert kW -> W)
        if unit_solar.lower() in ("kw", "kilowatt", "kilowatts"):
            df["solar_power_w"] = df["solar_power_w"] * 1000.0
            warnings.append("Converted solar_forecast from kW to Watts.")

        # Load units (convert kW -> W)
        if unit_load.lower() in ("kw", "kilowatt", "kilowatts"):
            df["load_power_w"] = df["load_power_w"] * 1000.0
            warnings.append("Converted load_forecast from kW to Watts.")

        # Price units (convert c/kWh or cents -> $/kWh)
        if unit_price.lower() in ("c/kwh", "cent/kwh", "cents", "cents/kwh"):
            df["buy_price"] = df["buy_price"] / 100.0
            df["sell_price"] = df["sell_price"] / 100.0
            warnings.append("Converted pricing from c/kWh to $/kWh.")

        return df, warnings
