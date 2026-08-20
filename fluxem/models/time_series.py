"""
Processed and standardized time series data structures using Pandas and NumPy.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


@dataclass
class ProcessedTimeSeriesData:
    """
    Encapsulates validated, normalized, and uniformly sampled time series data
    ready for optimization and analysis.
    """
    df: pd.DataFrame
    timestep_minutes: int
    timezone_name: str = "UTC"

    @property
    def timestamps(self) -> List[datetime]:
        """List of Python datetime objects for each timestep."""
        return [ts.to_pydatetime() for ts in self.df.index]

    @property
    def timestamps_iso(self) -> List[str]:
        """List of ISO-8601 formatted timestamp strings."""
        return [ts.isoformat() for ts in self.df.index]

    @property
    def total_steps(self) -> int:
        """Total number of forecast intervals."""
        return len(self.df)

    @property
    def timestep_hours(self) -> float:
        """Interval duration in hours (e.g., 0.5 for 30 minutes)."""
        return self.timestep_minutes / 60.0

    @property
    def horizon_hours(self) -> float:
        """Total horizon duration in hours."""
        return self.total_steps * self.timestep_hours

    @property
    def buy_prices(self) -> List[float]:
        """List of grid buy prices ($/kWh)."""
        return self.df["buy_price"].tolist()

    @property
    def sell_prices(self) -> List[float]:
        """List of grid sell/feed-in prices ($/kWh)."""
        return self.df["sell_price"].tolist()

    @property
    def solar_powers(self) -> List[float]:
        """List of solar power forecasts in Watts."""
        return self.df["solar_power_w"].tolist()

    @property
    def load_powers(self) -> List[float]:
        """List of baseline home load forecasts in Watts."""
        return self.df["load_power_w"].tolist()

    @property
    def net_loads(self) -> List[float]:
        """List of net load powers (load - solar) in Watts."""
        return self.df["net_load_power_w"].tolist()

    @property
    def total_solar_energy_kwh(self) -> float:
        """Total forecasted solar energy generation in kWh over the entire horizon."""
        if self.df.empty:
            return 0.0
        return float((self.df["solar_power_w"].sum() * self.timestep_hours) / 1000.0)

    @property
    def total_load_energy_kwh(self) -> float:
        """Total forecasted baseline household consumption in kWh over the entire horizon."""
        if self.df.empty:
            return 0.0
        return float((self.df["load_power_w"].sum() * self.timestep_hours) / 1000.0)

    @property
    def min_buy_price(self) -> float:
        return float(self.df["buy_price"].min()) if not self.df.empty else 0.0

    @property
    def max_buy_price(self) -> float:
        return float(self.df["buy_price"].max()) if not self.df.empty else 0.0

    @property
    def avg_buy_price(self) -> float:
        return float(self.df["buy_price"].mean()) if not self.df.empty else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Export as dictionary suitable for JSON responses and logging."""
        return {
            "total_steps": self.total_steps,
            "timestep_minutes": self.timestep_minutes,
            "horizon_hours": round(self.horizon_hours, 2),
            "start_time": self.timestamps_iso[0] if self.timestamps_iso else None,
            "end_time": self.timestamps_iso[-1] if self.timestamps_iso else None,
            "total_solar_kwh": round(self.total_solar_energy_kwh, 3),
            "total_load_kwh": round(self.total_load_energy_kwh, 3),
            "min_buy_price": round(self.min_buy_price, 4),
            "max_buy_price": round(self.max_buy_price, 4),
            "avg_buy_price": round(self.avg_buy_price, 4),
        }
