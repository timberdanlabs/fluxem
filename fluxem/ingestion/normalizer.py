"""
Data normalizer and time-series alignment for Agnostic Data Ingestion.
Performs frequency detection, uniform interval resampling, and computed feature derivations.
"""

from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from fluxem.models.time_series import ProcessedTimeSeriesData


class TimeSeriesNormalizer:
    """
    Normalizes time series to a uniform grid resolution and computes derived power curves.
    """

    @classmethod
    def normalize(
        cls,
        df: pd.DataFrame,
        target_timestep_minutes: Optional[int] = None,
        default_timestep_minutes: int = 30,
        timezone_name: Optional[str] = None,
    ) -> Tuple[ProcessedTimeSeriesData, List[str]]:
        """
        Detects timestep, optionally resamples to uniform resolution,
        and constructs ProcessedTimeSeriesData with derived columns.
        """
        warnings: List[str] = []
        df = df.copy()

        # 1. Detect native interval
        detected_timestep_minutes = cls.detect_interval_minutes(df, default_fallback=default_timestep_minutes)

        # 2. Decide effective timestep
        effective_timestep = target_timestep_minutes or detected_timestep_minutes

        # 3. Check if resampling is needed
        if target_timestep_minutes and (target_timestep_minutes != detected_timestep_minutes):
            warnings.append(
                f"Resampling time series from detected resolution ({detected_timestep_minutes} min) "
                f"to target resolution ({effective_timestep} min)."
            )
            df = cls.resample_dataframe(df, freq_minutes=effective_timestep)
        else:
            # Even without explicit resampling, ensure regular frequency grid if timestamps are slightly jittered
            time_diffs = (df.index[1:] - df.index[:-1]).total_seconds() / 60.0
            is_irregular = (np.abs(time_diffs - effective_timestep) > 0.5).any()
            if is_irregular:
                warnings.append(
                    f"Irregular interval spacing detected. Aligning timestamps to uniform {effective_timestep}-minute grid."
                )
                df = cls.resample_dataframe(df, freq_minutes=effective_timestep)

        # 4. Compute Derived Energy Features
        df["net_load_power_w"] = df["load_power_w"] - df["solar_power_w"]
        df["price_spread"] = df["buy_price"] - df["sell_price"]

        processed_data = ProcessedTimeSeriesData(
            df=df,
            timestep_minutes=effective_timestep,
            timezone_name=timezone_name or "UTC",
        )

        return processed_data, warnings

    @classmethod
    def detect_interval_minutes(cls, df: pd.DataFrame, default_fallback: int = 30) -> int:
        """
        Detects the dominant interval in minutes between consecutive timestamps using the median difference.
        """
        if len(df) < 2:
            return default_fallback

        diffs_sec = (df.index[1:] - df.index[:-1]).total_seconds()
        median_sec = float(np.median(diffs_sec))
        median_min = int(round(median_sec / 60.0))

        # Sanity check standard intervals (1, 5, 10, 15, 30, 60 min)
        if median_min in (1, 5, 10, 15, 30, 60):
            return median_min

        # Fallback to nearest reasonable interval or default
        if median_min > 0:
            return median_min
        return default_fallback

    @classmethod
    def resample_dataframe(cls, df: pd.DataFrame, freq_minutes: int) -> pd.DataFrame:
        """
        Resamples a DataFrame to a uniform frequency using physics-appropriate interpolation:
        - Prices: step-wise / forward-fill
        - Solar: linear interpolation with 0.0 lower bound
        - Load: linear interpolation with 0.0 lower bound
        """
        freq_str = f"{freq_minutes}min"

        # Create target uniform index from first timestamp to last timestamp
        target_index = pd.date_range(
            start=df.index[0],
            end=df.index[-1],
            freq=freq_str,
            tz=df.index.tz,
        )

        # Reindex and interpolate
        combined_index = df.index.union(target_index).sort_values()
        reindexed = df.reindex(combined_index)

        # Step-wise for price
        reindexed["buy_price"] = reindexed["buy_price"].ffill().bfill()
        reindexed["sell_price"] = reindexed["sell_price"].ffill().bfill()

        # Linear interpolation for power
        reindexed["solar_power_w"] = reindexed["solar_power_w"].interpolate(method="time").ffill().bfill().clip(lower=0.0)
        reindexed["load_power_w"] = reindexed["load_power_w"].interpolate(method="time").ffill().bfill().clip(lower=0.0)

        # Select only the target regular grid points
        resampled = reindexed.loc[target_index].copy()
        resampled.index.name = "timestamp"
        return resampled
