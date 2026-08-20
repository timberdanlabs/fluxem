"""
FluxEM Optimization Engine Coordinator.
Coordinates deferrable load scheduling (Module B), battery pre-charging & arbitrage (Module C),
and comprehensive schedule compilation.
"""

import time
from typing import Any, Dict, List, Optional
import numpy as np

from fluxem.ingestion.pipeline import StandardizedEnergyContext
from fluxem.models.response import OptimizationScheduleResponse
from fluxem.optimization.battery import BatteryScheduler
from fluxem.optimization.loads import DeferrableLoadScheduler


class OptimizationEngine:
    """
    Main Optimization Coordinator executing Modules B, C, and D.
    """

    def __init__(self):
        self.load_scheduler = DeferrableLoadScheduler()
        self.battery_scheduler = BatteryScheduler()

    def optimize(
        self,
        context: StandardizedEnergyContext,
        enable_export_arbitrage: Optional[bool] = None,
        min_arbitrage_profit_per_kwh: Optional[float] = None,
        battery_degradation_cost_per_kwh: Optional[float] = None,
        max_grid_export_power_w: Optional[float] = None,
    ) -> OptimizationScheduleResponse:
        """
        Executes optimization over the provided StandardizedEnergyContext.
        """
        start_ts = time.perf_counter()
        time_series = context.time_series
        total_steps = time_series.total_steps
        dt_hours = time_series.timestep_hours

        all_warnings = list(context.warnings)

        # Fallback to context metadata if arguments not explicitly passed
        eff_enable_export_arbitrage = (
            enable_export_arbitrage
            if enable_export_arbitrage is not None
            else context.metadata.get("enable_export_arbitrage")
        )
        eff_min_arbitrage_profit = (
            min_arbitrage_profit_per_kwh
            if min_arbitrage_profit_per_kwh is not None
            else context.metadata.get("min_arbitrage_profit_per_kwh")
        )
        eff_battery_deg_cost = (
            battery_degradation_cost_per_kwh
            if battery_degradation_cost_per_kwh is not None
            else context.metadata.get("battery_degradation_cost_per_kwh")
        )
        eff_max_grid_export = (
            max_grid_export_power_w
            if max_grid_export_power_w is not None
            else context.metadata.get("max_grid_export_power_w")
        )

        # 1. Module B: Schedule Deferrable Loads
        deferrable_schedules, combined_def_power, load_warnings = self.load_scheduler.schedule_all(
            loads=context.deferrable_loads,
            time_series=time_series,
        )
        all_warnings.extend(load_warnings)

        # Calculate Deferrable Energy & Cost Metrics
        baseline_load = np.array(time_series.load_powers)
        solar_power = np.array(time_series.solar_powers)
        def_power = np.array(combined_def_power)
        buy_prices = np.array(time_series.buy_prices)
        sell_prices = np.array(time_series.sell_prices)

        total_deferrable_kwh = float(np.sum(def_power) * dt_hours / 1000.0)

        deferrable_cost = 0.0
        for load_id, curve in deferrable_schedules.items():
            curve_arr = np.array(curve)
            step_import = np.maximum(0.0, baseline_load + curve_arr - solar_power) - np.maximum(0.0, baseline_load - solar_power)
            step_solar_used = curve_arr - step_import
            cost = (step_import * buy_prices + step_solar_used * sell_prices) * (dt_hours / 1000.0)
            deferrable_cost += float(np.sum(cost))

        # 2. Module C: Schedule Battery (Pre-charging, solar self-consumption, arbitrage)
        battery_power_curve: Optional[List[float]] = None
        battery_soc_curve: Optional[List[float]] = None
        grid_import_curve: List[float] = []
        grid_export_curve: List[float] = []
        battery_metrics: Dict[str, Any] = {}

        if context.battery is not None:
            battery_result = self.battery_scheduler.schedule(
                battery=context.battery,
                time_series=time_series,
                combined_deferrable_power_w=combined_def_power,
                enable_export_arbitrage=eff_enable_export_arbitrage,
                min_arbitrage_profit_per_kwh=eff_min_arbitrage_profit,
                battery_degradation_cost_per_kwh=eff_battery_deg_cost,
                max_grid_export_power_w=eff_max_grid_export,
            )
            battery_power_curve = battery_result.battery_power_w
            battery_soc_curve = battery_result.battery_soc_percent
            grid_import_curve = battery_result.grid_import_power_w
            grid_export_curve = battery_result.grid_export_power_w
            all_warnings.extend(battery_result.warnings)

            battery_metrics = {
                "solar_charged_kwh": battery_result.solar_charged_kwh,
                "grid_precharged_kwh": battery_result.grid_precharged_kwh,
                "home_discharged_kwh": battery_result.home_discharged_kwh,
                "arbitrage_exported_kwh": battery_result.arbitrage_exported_kwh,
                "final_soc_percent": battery_result.final_soc_percent,
                "grid_precharge_power_w": battery_result.grid_precharge_power_w,
                "arbitrage_export_power_w": battery_result.arbitrage_export_power_w,
            }
        else:
            # Simple grid balance without battery
            total_household_load = baseline_load + def_power
            net_power = total_household_load - solar_power
            grid_import_curve = np.maximum(0.0, net_power).tolist()
            grid_export_curve = np.maximum(0.0, -net_power).tolist()

        elapsed_ms = (time.perf_counter() - start_ts) * 1000.0

        # Construct summary response with merged warnings
        summary_response = context.to_summary_response()
        summary_response.warnings = all_warnings

        return OptimizationScheduleResponse(
            status="optimized",
            execution_time_ms=round(elapsed_ms, 2),
            timestamps=time_series.timestamps_iso,
            solar_forecast_w=time_series.solar_powers,
            baseline_load_w=time_series.load_powers,
            buy_prices=time_series.buy_prices,
            sell_prices=time_series.sell_prices,
            deferrable_load_power_w=deferrable_schedules,
            battery_power_w=battery_power_curve,
            battery_soc_percent=battery_soc_curve,
            grid_import_power_w=grid_import_curve,
            grid_export_power_w=grid_export_curve,
            summary=summary_response,
            metadata={
                "total_deferrable_energy_kwh": round(total_deferrable_kwh, 3),
                "estimated_deferrable_cost": round(deferrable_cost, 4),
                "battery_summary": battery_metrics,
                "module_status": {
                    "ingestion": "complete",
                    "deferrable_loads": "optimized",
                    "battery_arbitrage": "optimized" if context.battery else "no_battery",
                    "watchdog": "pending_module_d",
                },
            },
        )
