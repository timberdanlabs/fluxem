"""
Drift-Triggered MPC Watchdog Engine (Module D).
Monitors real-time observed telemetry against forecasted curves and decides whether
to trigger full re-optimization or hold the baseline plan.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional

from fluxem.config import settings
from fluxem.ingestion.pipeline import StandardizedEnergyContext
from fluxem.models.response import OptimizationScheduleResponse
from fluxem.watchdog.models import DriftMetric, WatchdogDecision

logger = logging.getLogger("fluxem.watchdog")


class DriftWatchdog:
    """
    Intelligent watchdog comparing real-time observed sensors with forecast baseline curves.
    """

    def __init__(
        self,
        solar_drift_threshold_pct: Optional[float] = None,
        price_drift_threshold_pct: Optional[float] = None,
        load_drift_threshold_pct: Optional[float] = None,
        soc_drift_threshold_pct: float = 10.0,
    ):
        self.solar_threshold_pct = (
            solar_drift_threshold_pct
            if solar_drift_threshold_pct is not None
            else settings.solar_drift_threshold_pct
        )
        self.price_threshold_pct = (
            price_drift_threshold_pct
            if price_drift_threshold_pct is not None
            else settings.price_drift_threshold_pct
        )
        self.load_threshold_pct = (
            load_drift_threshold_pct
            if load_drift_threshold_pct is not None
            else settings.load_drift_threshold_pct
        )
        self.soc_threshold_pct = soc_drift_threshold_pct

        # In-memory cached active plan and timestamp
        self._cached_plan: Optional[OptimizationScheduleResponse] = None
        self._last_optimized_at: Optional[datetime] = None

    @property
    def cached_plan(self) -> Optional[OptimizationScheduleResponse]:
        """Returns the currently active cached plan."""
        return self._cached_plan

    def update_cached_plan(self, plan: OptimizationScheduleResponse):
        """Stores a newly computed plan in the watchdog cache."""
        self._cached_plan = plan
        self._last_optimized_at = datetime.now(timezone.utc)
        logger.info("Watchdog cached baseline plan updated.")

    def clear_cache(self):
        """Resets the cached plan."""
        self._cached_plan = None
        self._last_optimized_at = None

    def evaluate(
        self,
        context: StandardizedEnergyContext,
        force_reoptimize: bool = False,
    ) -> WatchdogDecision:
        """
        Evaluates real-time sensor measurements against forecast and decides
        whether to trigger a full re-optimization sweep or hold the existing plan.
        """
        # 1. Check for explicit force trigger
        if force_reoptimize:
            return WatchdogDecision(
                should_reoptimize=True,
                reason="Forced re-optimization requested by user/automation.",
                metrics={},
                breached_metrics=[],
            )

        # 2. Check if a valid cached plan exists
        if self._cached_plan is None:
            return WatchdogDecision(
                should_reoptimize=True,
                reason="No active baseline plan in memory. Full baseline optimization sweep required.",
                metrics={},
                breached_metrics=[],
            )

        # 3. Check for plan expiry (> 24 hours old)
        if self._last_optimized_at:
            age_hours = (datetime.now(timezone.utc) - self._last_optimized_at).total_seconds() / 3600.0
            if age_hours >= 24.0:
                return WatchdogDecision(
                    should_reoptimize=True,
                    reason=f"Previous baseline plan expired ({age_hours:.1f}h old). Daily refresh required.",
                    metrics={},
                    breached_metrics=[],
                )

        metrics: Dict[str, DriftMetric] = {}
        breached_metrics: List[str] = []

        # --- A. Solar Generation Drift ---
        actual_solar = context.actual_sensors.get("solar_power_w")
        forecast_solar = context.time_series.solar_powers[0] if context.time_series.solar_powers else 0.0

        if actual_solar is not None:
            # If both actual and forecast are negligible (night time / cloud edge < 100W), ignore drift
            if actual_solar < 100.0 and forecast_solar < 100.0:
                solar_drift_pct = 0.0
            else:
                denom = max(forecast_solar, 200.0)
                solar_drift_pct = (abs(actual_solar - forecast_solar) / denom) * 100.0

            solar_breached = solar_drift_pct > self.solar_threshold_pct
            metrics["solar_drift"] = DriftMetric(
                name="Solar Drift",
                actual_value=round(actual_solar, 1),
                forecast_value=round(forecast_solar, 1),
                drift_pct=round(solar_drift_pct, 1),
                threshold_pct=self.solar_threshold_pct,
                is_breached=solar_breached,
                unit="W",
            )
            if solar_breached:
                breached_metrics.append(
                    f"Solar Generation Drift ({solar_drift_pct:.1f}% > {self.solar_threshold_pct:.1f}%)"
                )

        # --- B. Electricity Buy Price Drift ---
        actual_price = context.actual_sensors.get("buy_price")
        forecast_price = context.time_series.buy_prices[0] if context.time_series.buy_prices else 0.0

        if actual_price is not None:
            denom = max(abs(forecast_price), 0.05)
            price_drift_pct = (abs(actual_price - forecast_price) / denom) * 100.0
            price_breached = price_drift_pct > self.price_threshold_pct

            metrics["price_drift"] = DriftMetric(
                name="Price Drift",
                actual_value=round(actual_price, 4),
                forecast_value=round(forecast_price, 4),
                drift_pct=round(price_drift_pct, 1),
                threshold_pct=self.price_threshold_pct,
                is_breached=price_breached,
                unit="$/kWh",
            )
            if price_breached:
                breached_metrics.append(
                    f"Buy Price Drift ({price_drift_pct:.1f}% > {self.price_threshold_pct:.1f}%)"
                )

        # --- C. Baseline Household Load Drift ---
        # Use pure decomposed baseline load (from Zero-Helper Module A)
        actual_load = (
            context.actual_baseline_load_w
            if context.actual_baseline_load_w is not None
            else context.actual_sensors.get("total_house_power_w")
        )
        forecast_load = context.time_series.load_powers[0] if context.time_series.load_powers else 0.0

        if actual_load is not None:
            denom = max(forecast_load, 300.0)
            load_drift_pct = (abs(actual_load - forecast_load) / denom) * 100.0
            load_breached = load_drift_pct > self.load_threshold_pct

            metrics["load_drift"] = DriftMetric(
                name="Baseline Load Drift",
                actual_value=round(actual_load, 1),
                forecast_value=round(forecast_load, 1),
                drift_pct=round(load_drift_pct, 1),
                threshold_pct=self.load_threshold_pct,
                is_breached=load_breached,
                unit="W",
            )
            if load_breached:
                breached_metrics.append(
                    f"Baseline Load Drift ({load_drift_pct:.1f}% > {self.load_threshold_pct:.1f}%)"
                )

        # --- D. Battery SOC Drift ---
        if context.battery is not None and self._cached_plan and self._cached_plan.battery_soc_percent:
            actual_soc = context.battery.soc_percent
            # Align with step 0 of current plan
            forecast_soc = self._cached_plan.battery_soc_percent[0]
            soc_diff_pct = abs(actual_soc - forecast_soc)
            soc_breached = soc_diff_pct > self.soc_threshold_pct

            metrics["battery_soc_drift"] = DriftMetric(
                name="Battery SOC Drift",
                actual_value=round(actual_soc, 1),
                forecast_value=round(forecast_soc, 1),
                drift_pct=round(soc_diff_pct, 1),
                threshold_pct=self.soc_threshold_pct,
                is_breached=soc_breached,
                unit="%",
            )
            if soc_breached:
                breached_metrics.append(
                    f"Battery SOC Drift ({soc_diff_pct:.1f}% > {self.soc_threshold_pct:.1f}%)"
                )

        # 4. Final Decision Formulation
        if len(breached_metrics) > 0:
            return WatchdogDecision(
                should_reoptimize=True,
                reason=f"Re-optimization triggered by drift variance: {'; '.join(breached_metrics)}.",
                metrics=metrics,
                breached_metrics=breached_metrics,
            )
        else:
            return WatchdogDecision(
                should_reoptimize=False,
                reason="All real-time sensors within configured variance tolerances. Holding active baseline plan.",
                metrics=metrics,
                breached_metrics=[],
            )
