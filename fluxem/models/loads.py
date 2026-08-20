"""
Deferrable load configuration and runtime state models.
"""

from typing import Optional
from pydantic import BaseModel, Field, model_validator


class DeferrableLoad(BaseModel):
    """
    Configuration and real-time state for a deferrable appliance
    (e.g., hot water system, pool pump, EV charger, heat pump).
    """
    id: str = Field(
        ...,
        description="Unique identifier for the deferrable load (e.g., 'water_heater', 'pool_pump')",
        examples=["water_heater"],
    )
    name: Optional[str] = Field(
        default=None,
        description="Human-friendly label for display and logging",
        examples=["Heat Pump Water Heater"],
    )
    nominal_power_w: float = Field(
        ...,
        gt=0.0,
        description="Nominal operating power draw in Watts when active",
        examples=[3700.0],
    )
    current_power_w: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Real-time measured power consumption in Watts from a dedicated sub-meter/smart plug",
        examples=[3680.0],
    )
    is_included_in_total_load: bool = Field(
        default=True,
        description="Whether this appliance's power consumption is included in the whole-home house_power sensor reading",
        examples=[True],
    )
    required_hours: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total operating runtime required in hours for the planning period",
        examples=[3.5],
    )
    required_kwh: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total energy required in kWh (alternative or supplementary to required_hours)",
        examples=[8.4],
    )
    continuous: bool = Field(
        default=False,
        description="If True, requires an unbroken, contiguous run block once initiated (e.g., hot water)",
        examples=[True],
    )
    is_running: bool = Field(
        default=False,
        description="Real-time observed state: True if the appliance is actively running right now",
        examples=[False],
    )
    accumulated_hours_today: float = Field(
        default=0.0,
        ge=0.0,
        description="Runtime hours already consumed/completed today prior to this optimization run",
        examples=[1.0],
    )
    window_start_time: Optional[str] = Field(
        default=None,
        description="Earliest permissible start time (e.g. '08:00' or ISO timestamp)",
        examples=["08:00"],
    )
    window_end_time: Optional[str] = Field(
        default=None,
        description="Latest permissible completion time (e.g. '18:00' or ISO timestamp)",
        examples=["18:00"],
    )
    max_starts_per_day: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum number of start/stop cycles permitted per day (for flexible loads)",
        examples=[3],
    )
    priority: int = Field(
        default=1,
        ge=1,
        description="Load priority ranking (1 = standard, higher numbers = higher priority)",
        examples=[1],
    )
    power_sensor_entity_id: Optional[str] = Field(
        default=None,
        description="Home Assistant entity ID for real-time power monitoring (e.g. sensor.water_heater_power)",
        examples=["sensor.water_heater_power"],
    )
    switch_entity_id: Optional[str] = Field(
        default=None,
        description="Home Assistant switch entity ID for state control (e.g. switch.water_heater)",
        examples=["switch.water_heater"],
    )

    @model_validator(mode="after")
    def validate_requirements(self) -> "DeferrableLoad":
        # Resolve required_hours and required_kwh
        if self.required_hours is None and self.required_kwh is None:
            raise ValueError(f"Load '{self.id}' must specify either 'required_hours' or 'required_kwh'")

        if self.required_hours is None and self.required_kwh is not None:
            self.required_hours = self.required_kwh / (self.nominal_power_w / 1000.0)
        elif self.required_kwh is None and self.required_hours is not None:
            self.required_kwh = self.required_hours * (self.nominal_power_w / 1000.0)

        if not self.name:
            self.name = self.id.replace("_", " ").title()

        # If current_power_w is reported and > 0, auto-infer is_running if not explicitly provided
        if self.current_power_w is not None and self.current_power_w > 10.0:
            self.is_running = True

        return self

    @property
    def active_power_w(self) -> float:
        """
        Active power draw in Watts right now.
        Uses exact current_power_w sensor if available; otherwise uses nominal_power_w if is_running is True.
        """
        if self.current_power_w is not None and self.current_power_w >= 0:
            return float(self.current_power_w)
        if self.is_running:
            return float(self.nominal_power_w)
        return 0.0

    @property
    def remaining_hours_needed(self) -> float:
        """Operating hours still needed today after accounting for accumulated runtime."""
        if self.required_hours is None:
            return 0.0
        return max(0.0, self.required_hours - self.accumulated_hours_today)

    @property
    def remaining_energy_kwh_needed(self) -> float:
        """Energy in kWh still needed today."""
        return self.remaining_hours_needed * (self.nominal_power_w / 1000.0)

    @property
    def is_satisfied(self) -> bool:
        """True if the daily requirement has already been satisfied."""
        return self.remaining_hours_needed <= 1e-6
