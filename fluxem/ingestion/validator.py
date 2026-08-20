"""
Data validator for the Agnostic Data Ingestion module.
Performs data consistency, integrity, NaN imputation, and sanity checks.
"""

from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from fluxem.models.battery import BatteryState
from fluxem.models.loads import DeferrableLoad


class DataValidator:
    """
    Validates and cleans time-series dataframes, battery configurations,
    and deferrable load constraints.
    """

    @classmethod
    def validate_and_clean(
        cls,
        df: pd.DataFrame,
        battery: Optional[BatteryState] = None,
        deferrable_loads: Optional[List[DeferrableLoad]] = None,
        min_horizon_hours: float = 2.0,
        max_horizon_hours: float = 72.0,
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Validates, cleans, and imputes missing/invalid values in the dataframe.
        Returns cleaned DataFrame and list of warnings.
        """
        warnings: List[str] = []

        if df.empty:
            raise ValueError("Input time-series data is empty.")

        if len(df) < 2:
            raise ValueError(f"At least 2 time steps are required, got {len(df)}.")

        # 1. Check for Duplicate Timestamps
        if df.index.has_duplicates:
            dup_count = df.index.duplicated().sum()
            warnings.append(f"Found {dup_count} duplicate timestamps. Deduplicating by averaging values.")
            df = df.groupby(df.index).mean()

        # 2. Check Timestamp Monotonicity
        if not df.index.is_monotonic_increasing:
            warnings.append("Timestamps were not in chronological order. Sorted timestamps automatically.")
            df = df.sort_index()

        # 3. Handle NaNs and Infs in Time Series
        # Check for Infinite values
        if np.isinf(df.to_numpy()).any():
            warnings.append("Infinite values detected in time series. Replacing with NaNs for imputation.")
            df = df.replace([np.inf, -np.inf], np.nan)

        # Impute Missing Buy Prices (Forward Fill -> Backward Fill)
        if df["buy_price"].isna().any():
            nan_count = int(df["buy_price"].isna().sum())
            warnings.append(f"Imputed {nan_count} missing/NaN buy price values using forward/backward fill.")
            df["buy_price"] = df["buy_price"].ffill().bfill().fillna(0.20)

        # Impute Missing Sell Prices
        if df["sell_price"].isna().any():
            nan_count = int(df["sell_price"].isna().sum())
            warnings.append(f"Imputed {nan_count} missing/NaN sell price values with 0.00 $/kWh.")
            df["sell_price"] = df["sell_price"].fillna(0.0)

        # Impute Missing Solar Forecast (Linear interpolation, fill 0.0 at night/bounds)
        if df["solar_power_w"].isna().any():
            nan_count = int(df["solar_power_w"].isna().sum())
            warnings.append(f"Imputed {nan_count} missing solar forecast values with 0.0 W.")
            df["solar_power_w"] = df["solar_power_w"].interpolate(method="time").fillna(0.0)

        # Impute Missing Load Forecast (Linear interpolation, fill forward/mean)
        if df["load_power_w"].isna().any():
            nan_count = int(df["load_power_w"].isna().sum())
            warnings.append(f"Imputed {nan_count} missing load forecast values using interpolation.")
            df["load_power_w"] = df["load_power_w"].interpolate(method="time").ffill().bfill().fillna(500.0)

        # 4. Physical Plausibility Constraints
        # Solar generation cannot be negative
        if (df["solar_power_w"] < 0).any():
            warnings.append("Negative solar power values detected. Clamping to 0.0 W.")
            df["solar_power_w"] = df["solar_power_w"].clip(lower=0.0)

        # Baseline home load cannot be negative
        if (df["load_power_w"] < 0).any():
            warnings.append("Negative home load values detected. Clamping to 0.0 W.")
            df["load_power_w"] = df["load_power_w"].clip(lower=0.0)

        # 5. Horizon Length Checks
        time_diff = df.index[-1] - df.index[0]
        horizon_hours = time_diff.total_seconds() / 3600.0

        if horizon_hours < min_horizon_hours:
            warnings.append(
                f"Short horizon span detected: {horizon_hours:.2f} hours (recommended minimum: {min_horizon_hours}h)."
            )
        elif horizon_hours > max_horizon_hours:
            warnings.append(
                f"Long horizon span detected: {horizon_hours:.2f} hours (configured maximum: {max_horizon_hours}h)."
            )

        # 6. Validate Battery Constraints
        if battery is not None:
            battery_warnings = cls._validate_battery(battery)
            warnings.extend(battery_warnings)

        # 7. Validate Deferrable Loads
        if deferrable_loads:
            load_warnings = cls._validate_loads(deferrable_loads)
            warnings.extend(load_warnings)

        return df, warnings

    @classmethod
    def _validate_battery(cls, battery: BatteryState) -> List[str]:
        warnings: List[str] = []
        if battery.capacity_kwh <= 0:
            warnings.append(f"Invalid battery capacity {battery.capacity_kwh} kWh. Must be > 0.")
        if battery.soc_percent < battery.min_soc_percent:
            warnings.append(
                f"Current battery SOC ({battery.soc_percent:.1f}%) is below configured min_soc ({battery.min_soc_percent:.1f}%)."
            )
        if battery.max_charge_power_w <= 0:
            warnings.append("Battery max_charge_power_w is <= 0 W; battery will not be able to charge.")
        if battery.max_discharge_power_w <= 0:
            warnings.append("Battery max_discharge_power_w is <= 0 W; battery will not be able to discharge.")
        return warnings

    @classmethod
    def _validate_loads(cls, loads: List[DeferrableLoad]) -> List[str]:
        warnings: List[str] = []
        seen_ids = set()
        for load in loads:
            if load.id in seen_ids:
                warnings.append(f"Duplicate deferrable load ID '{load.id}' detected.")
            seen_ids.add(load.id)

            if load.accumulated_hours_today >= (load.required_hours or 0.0) and (load.required_hours or 0.0) > 0:
                warnings.append(
                    f"Load '{load.id}' requirement ({load.required_hours:.1f}h) has already been satisfied today "
                    f"({load.accumulated_hours_today:.1f}h completed)."
                )
        return warnings
