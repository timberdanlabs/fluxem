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
    critical: bool = Field(
        default=True,
        description="If True, mandatory daily run (must satisfy required quota every day, using grid power if necessary). "
                    "If False, opportunistic run that can be deferred/skipped on expensive or low-solar days.",
        examples=[True],
    )
    max_skip_days: Optional[int] = Field(
        default=1,
        ge=0,
        description="Maximum consecutive days an opportunistic load can be skipped before being forced to run (e.g. 1 = can skip at most 1 day)",
        examples=[1],
    )
    consecutive_days_skipped: int = Field(
        default=0,
        ge=0,
        description="Runtime tracking: number of consecutive days this load has already been skipped prior to today",
        examples=[0],
    )
    max_buy_price: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Maximum retail grid import price ($/kWh) the load will accept when importing from grid (for opportunistic runs)",
        examples=[0.20],
    )
    solar_only: bool = Field(
        default=False,
        description="If True, the load will strictly only run when surplus solar power is available (no grid import)",
        examples=[False],
    )
    min_solar_power_w: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Minimum gross solar power generation (Watts) required to run (e.g. to ensure solar roof collectors are hot)",
        examples=[2500.0],
    )
    dynamic_solar_quota: bool = Field(
        default=False,
        description="If True, dynamically schedules all available qualifying solar surplus intervals (up to optional max_daily_hours) instead of requiring a fixed required_hours quota",
        examples=[True],
    )
    max_daily_hours: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Optional maximum operating hours per day when dynamic_solar_quota is enabled (None = unlimited sun-tracking)",
        examples=[6.0],
    )
    min_run_time_minutes: Optional[int] = Field(
        default=None,
        ge=0,
        description="Minimum duration in minutes for any scheduled continuous run block (anti-short-cycling)",
        examples=[30],
    )
    complete_on_cutoff: bool = Field(
        default=False,
        description="If True, automatically marks today's requirement as satisfied when power consumption drops to 0W (idle) after an active heating cycle (e.g. water heater thermostat satisfied)",
        examples=[True],
    )
    is_cycle_completed_today: bool = Field(
        default=False,
        description="Runtime state: True if the appliance has completed its heating cycle / thermostat cutoff today",
        examples=[False],
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
        # Handle dynamic_solar_quota
        if self.dynamic_solar_quota:
            if "critical" in self.model_fields_set and self.critical:
                raise ValueError(f"Load '{self.id}' cannot have both 'critical: true' (mandatory grid run) and 'dynamic_solar_quota: true'.")
            self.critical = False
            self.solar_only = True
            if self.required_hours is None and self.max_daily_hours is not None:
                self.required_hours = self.max_daily_hours
        else:
            # Resolve required_hours and required_kwh for standard quota loads
            if self.required_hours is None and self.required_kwh is None:
                raise ValueError(f"Load '{self.id}' must specify either 'required_hours' or 'required_kwh'")

            if self.required_hours is None and self.required_kwh is not None:
                self.required_hours = self.required_kwh / (self.nominal_power_w / 1000.0)
            elif self.required_kwh is None and self.required_hours is not None:
                self.required_kwh = self.required_hours * (self.nominal_power_w / 1000.0)

        # Handle solar_only and critical interactions
        if self.solar_only:
            if "critical" in self.model_fields_set and self.critical:
                raise ValueError(f"Load '{self.id}' cannot have both 'critical: true' (mandatory grid run) and 'solar_only: true' (zero grid import).")
            self.critical = False

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
        """Operating hours still needed today after accounting for accumulated runtime or cycle completion."""
        if self.is_cycle_completed_today:
            return 0.0
        if self.dynamic_solar_quota:
            if self.max_daily_hours is not None:
                return max(0.0, self.max_daily_hours - self.accumulated_hours_today)
            return 0.0
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
        if self.is_cycle_completed_today:
            return True
        if self.dynamic_solar_quota:
            if self.max_daily_hours is not None:
                return self.accumulated_hours_today >= (self.max_daily_hours - 1e-6)
            return False
        return self.remaining_hours_needed <= 1e-6
