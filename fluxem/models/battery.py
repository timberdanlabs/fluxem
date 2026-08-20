"""
Battery models and state representations.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class BatteryState(BaseModel):
    """
    Representation of a home battery system state and operational limits.
    """
    soc_percent: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Current State of Charge percentage (0.0 to 100.0%)",
        examples=[65.5],
    )
    capacity_kwh: float = Field(
        ...,
        gt=0.0,
        description="Nominal or total battery storage capacity in kWh",
        examples=[13.5],
    )
    max_charge_power_w: float = Field(
        default=5000.0,
        ge=0.0,
        description="Maximum charging power rate in Watts",
        examples=[5000.0],
    )
    max_discharge_power_w: float = Field(
        default=5000.0,
        ge=0.0,
        description="Maximum discharging power rate in Watts",
        examples=[5000.0],
    )
    min_soc_percent: float = Field(
        default=10.0,
        ge=0.0,
        le=100.0,
        description="Minimum reserve SOC percentage to maintain (0.0 to 100.0%)",
        examples=[10.0],
    )
    max_soc_percent: float = Field(
        default=100.0,
        ge=0.0,
        le=100.0,
        description="Maximum target SOC percentage (0.0 to 100.0%)",
        examples=[100.0],
    )
    round_trip_efficiency: float = Field(
        default=0.90,
        gt=0.0,
        le=1.0,
        description="Round-trip charging/discharging energy efficiency (e.g. 0.90 for 90%)",
        examples=[0.90],
    )
    current_power_w: Optional[float] = Field(
        default=None,
        description="Current observed real-time battery power in Watts (positive = charging, negative = discharging)",
    )

    @field_validator("soc_percent", "min_soc_percent", "max_soc_percent", mode="before")
    @classmethod
    def normalize_fraction_to_percent(cls, v: float | int) -> float:
        """Handle values passed as fractions (e.g. 0.65 instead of 65.0)."""
        val = float(v)
        # If value is between 0.0 and 1.0 (and not exactly 0.0 or 1.0 if entered as 1.0),
        # keep standard percent check or convert if it looks like a ratio.
        # However, 1% is 1.0%, while 0.85 is clearly 85%. If v <= 1.0 and v > 0.0:
        # Note: to be safe, if a user passes 0.5 for a 50% battery, we convert.
        # But if they pass 0 or 100, we leave as is.
        if 0.0 < val < 1.0:
            return val * 100.0
        return val

    @model_validator(mode="after")
    def validate_min_max_soc(self) -> "BatteryState":
        if self.min_soc_percent > self.max_soc_percent:
            raise ValueError(
                f"min_soc_percent ({self.min_soc_percent}%) cannot exceed max_soc_percent ({self.max_soc_percent}%)"
            )
        return self

    @property
    def current_energy_kwh(self) -> float:
        """Current stored energy in kWh."""
        return (self.soc_percent / 100.0) * self.capacity_kwh

    @property
    def usable_capacity_kwh(self) -> float:
        """Total usable capacity between min_soc and max_soc in kWh."""
        return ((self.max_soc_percent - self.min_soc_percent) / 100.0) * self.capacity_kwh

    @property
    def available_discharge_energy_kwh(self) -> float:
        """Energy available for discharge down to min_soc_percent in kWh."""
        available_soc = max(0.0, self.soc_percent - self.min_soc_percent)
        return (available_soc / 100.0) * self.capacity_kwh

    @property
    def available_charge_energy_kwh(self) -> float:
        """Room available to charge up to max_soc_percent in kWh."""
        headroom_soc = max(0.0, self.max_soc_percent - self.soc_percent)
        return (headroom_soc / 100.0) * self.capacity_kwh
