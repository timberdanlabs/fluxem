"""
Intelligent Grid Pre-Charging and Dynamic Battery Arbitrage Engine (Module C).
Implements self-consumption look-ahead deficit pre-charging, wholesale feed-in arbitrage,
and physics-constrained battery state-of-charge simulation.
"""

from dataclasses import dataclass
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from fluxem.config import settings
from fluxem.models.battery import BatteryState
from fluxem.models.time_series import ProcessedTimeSeriesData

logger = logging.getLogger("fluxem.optimization.battery")


@dataclass
class BatterySimulationResult:
    """Detailed output of the battery optimization and simulation."""
    battery_power_w: List[float]       # Positive = charging (solar/grid), Negative = discharging (home/export)
    battery_soc_percent: List[float]   # SOC % curve at each step
    grid_import_power_w: List[float]   # Total grid import power curve
    grid_export_power_w: List[float]   # Total grid export power curve
    grid_precharge_power_w: List[float]# Grid pre-charging power curve (subset of import)
    arbitrage_export_power_w: List[float]# Dedicated wholesale arbitrage export power curve
    solar_charged_kwh: float           # Total solar energy charged into battery
    grid_precharged_kwh: float         # Total grid energy precharged into battery
    home_discharged_kwh: float         # Total battery energy discharged to serve home
    arbitrage_exported_kwh: float      # Total battery energy discharged to grid for arbitrage
    final_soc_percent: float           # Ending SOC %
    warnings: List[str]                # Optimization warnings and notes


class BatteryScheduler:
    """
    Simulates and optimizes home battery operations:
    1. Maximizes solar self-consumption
    2. Schedules intelligent off-peak grid pre-charging before expensive peak periods
    3. Executes dynamic wholesale export arbitrage when feed-in spikes exceed buy prices + margin
    """

    @classmethod
    def schedule(
        cls,
        battery: BatteryState,
        time_series: ProcessedTimeSeriesData,
        combined_deferrable_power_w: List[float],
        enable_export_arbitrage: Optional[bool] = None,
        min_arbitrage_profit_per_kwh: Optional[float] = None,
        battery_degradation_cost_per_kwh: Optional[float] = None,
        max_grid_export_power_w: Optional[float] = None,
    ) -> BatterySimulationResult:
        """
        Executes multi-pass look-ahead battery scheduling.
        """
        warnings: List[str] = []
        total_steps = time_series.total_steps
        dt_hours = time_series.timestep_hours

        # Configuration options
        export_arbitrage_enabled = (
            enable_export_arbitrage
            if enable_export_arbitrage is not None
            else settings.enable_export_arbitrage
        )
        min_profit = (
            min_arbitrage_profit_per_kwh
            if min_arbitrage_profit_per_kwh is not None
            else settings.min_arbitrage_profit_per_kwh
        )
        deg_cost = (
            battery_degradation_cost_per_kwh
            if battery_degradation_cost_per_kwh is not None
            else settings.battery_degradation_cost_per_kwh
        )
        max_export_power = (
            max_grid_export_power_w
            if max_grid_export_power_w is not None
            else (settings.max_grid_export_power_w or battery.max_discharge_power_w)
        )

        # Baseline Net Load Curve (Home baseline load + scheduled deferrable loads - solar)
        total_load = np.array(time_series.load_powers) + np.array(combined_deferrable_power_w)
        solar_power = np.array(time_series.solar_powers)
        net_load = total_load - solar_power  # > 0 means home deficit, < 0 means solar surplus

        buy_prices = np.array(time_series.buy_prices)
        sell_prices = np.array(time_series.sell_prices)

        # Round-trip efficiency breakdown (symmetric half-cycle efficiency)
        eta_rt = battery.round_trip_efficiency
        eta_chg = math.sqrt(eta_rt)
        eta_dis = math.sqrt(eta_rt)

        capacity_kwh = battery.capacity_kwh
        min_soc = battery.min_soc_percent / 100.0
        max_soc = battery.max_soc_percent / 100.0
        initial_soc = battery.soc_percent / 100.0

        max_charge_w = battery.max_charge_power_w
        max_discharge_w = battery.max_discharge_power_w

        # --- PASS 1: Baseline Solar Self-Consumption Simulation ---
        soc_pass1, grid_import_pass1, grid_export_pass1 = cls._simulate_forward(
            net_load=net_load,
            initial_soc=initial_soc,
            capacity_kwh=capacity_kwh,
            min_soc=min_soc,
            max_soc=max_soc,
            max_charge_w=max_charge_w,
            max_discharge_w=max_discharge_w,
            eta_chg=eta_chg,
            eta_dis=eta_dis,
            dt_hours=dt_hours,
            grid_precharge_w=np.zeros(total_steps),
            arbitrage_export_w=np.zeros(total_steps),
        )

        # --- PASS 2: Deficit Grid Pre-Charging (Smart Arbitrage) ---
        grid_precharge_w = np.zeros(total_steps)
        precharge_warnings = cls._plan_deficit_precharge(
            grid_import_pass1=grid_import_pass1,
            soc_curve=soc_pass1,
            buy_prices=buy_prices,
            capacity_kwh=capacity_kwh,
            min_soc=min_soc,
            max_soc=max_soc,
            max_charge_w=max_charge_w,
            eta_chg=eta_chg,
            eta_dis=eta_dis,
            dt_hours=dt_hours,
            total_steps=total_steps,
            grid_precharge_w=grid_precharge_w,
        )
        warnings.extend(precharge_warnings)

        # --- PASS 3: Dynamic Wholesale Export Arbitrage (Optional) ---
        arbitrage_export_w = np.zeros(total_steps)
        if export_arbitrage_enabled:
            # Re-simulate with pre-charge to get updated SOC headroom
            soc_pass2, _, _ = cls._simulate_forward(
                net_load=net_load,
                initial_soc=initial_soc,
                capacity_kwh=capacity_kwh,
                min_soc=min_soc,
                max_soc=max_soc,
                max_charge_w=max_charge_w,
                max_discharge_w=max_discharge_w,
                eta_chg=eta_chg,
                eta_dis=eta_dis,
                dt_hours=dt_hours,
                grid_precharge_w=grid_precharge_w,
                arbitrage_export_w=np.zeros(total_steps),
            )

            arb_warnings = cls._plan_export_arbitrage(
                buy_prices=buy_prices,
                sell_prices=sell_prices,
                soc_curve=soc_pass2,
                capacity_kwh=capacity_kwh,
                min_soc=min_soc,
                max_soc=max_soc,
                max_charge_w=max_charge_w,
                max_discharge_w=min(max_discharge_w, max_export_power),
                eta_rt=eta_rt,
                eta_chg=eta_chg,
                eta_dis=eta_dis,
                dt_hours=dt_hours,
                min_profit=min_profit,
                deg_cost=deg_cost,
                total_steps=total_steps,
                grid_precharge_w=grid_precharge_w,
                arbitrage_export_w=arbitrage_export_w,
            )
            warnings.extend(arb_warnings)

        # --- PASS 4: Final Precise Forward Simulation ---
        soc_final, grid_import_final, grid_export_final, batt_power_final, metrics = (
            cls._simulate_final(
                net_load=net_load,
                initial_soc=initial_soc,
                capacity_kwh=capacity_kwh,
                min_soc=min_soc,
                max_soc=max_soc,
                max_charge_w=max_charge_w,
                max_discharge_w=max_discharge_w,
                eta_chg=eta_chg,
                eta_dis=eta_dis,
                dt_hours=dt_hours,
                grid_precharge_w=grid_precharge_w,
                arbitrage_export_w=arbitrage_export_w,
            )
        )

        return BatterySimulationResult(
            battery_power_w=batt_power_final.tolist(),
            battery_soc_percent=[round(s * 100.0, 2) for s in soc_final],
            grid_import_power_w=grid_import_final.tolist(),
            grid_export_power_w=grid_export_final.tolist(),
            grid_precharge_power_w=grid_precharge_w.tolist(),
            arbitrage_export_power_w=arbitrage_export_w.tolist(),
            solar_charged_kwh=round(metrics["solar_charged_kwh"], 3),
            grid_precharged_kwh=round(metrics["grid_precharged_kwh"], 3),
            home_discharged_kwh=round(metrics["home_discharged_kwh"], 3),
            arbitrage_exported_kwh=round(metrics["arbitrage_exported_kwh"], 3),
            final_soc_percent=round(soc_final[-1] * 100.0, 2),
            warnings=warnings,
        )

    @classmethod
    def _plan_deficit_precharge(
        cls,
        grid_import_pass1: np.ndarray,
        soc_curve: np.ndarray,
        buy_prices: np.ndarray,
        capacity_kwh: float,
        min_soc: float,
        max_soc: float,
        max_charge_w: float,
        eta_chg: float,
        eta_dis: float,
        dt_hours: float,
        total_steps: int,
        grid_precharge_w: np.ndarray,
    ) -> List[str]:
        """
        Scans for expensive future grid imports that occur due to exhausted battery,
        and plans pre-charging during earlier cheap price windows if the price differential exceeds losses.
        """
        warnings: List[str] = []
        eta_rt = eta_chg * eta_dis

        # Find steps where home is forced to import power
        deficit_steps = np.where(grid_import_pass1 > 10.0)[0]
        if len(deficit_steps) == 0:
            return warnings

        # Sort deficit steps by highest buy price first
        sorted_deficits = sorted(deficit_steps, key=lambda t: buy_prices[t], reverse=True)

        for t_peak in sorted_deficits:
            p_peak_buy = buy_prices[t_peak]
            import_needed_w = grid_import_pass1[t_peak]
            if import_needed_w <= 10.0:
                continue

            # Target energy needed at peak (kWh at output of battery)
            energy_needed_kwh = (import_needed_w * dt_hours) / 1000.0

            # Look for earlier steps t_chg < t_peak where precharging is profitable:
            # Profit condition: buy_price(t_chg) < eta_rt * buy_price(t_peak)
            candidate_chg_steps = []
            for t_chg in range(0, t_peak):
                p_chg_buy = buy_prices[t_chg]
                # Price spread must cover round-trip losses
                if p_chg_buy < (p_peak_buy * eta_rt - 0.01):
                    candidate_chg_steps.append(t_chg)

            if not candidate_chg_steps:
                continue

            # Sort candidate charge steps by lowest buy price
            candidate_chg_steps.sort(key=lambda t: buy_prices[t])

            for t_chg in candidate_chg_steps:
                if energy_needed_kwh <= 1e-4:
                    break

                # Available charging headroom at t_chg
                existing_precharge = grid_precharge_w[t_chg]
                headroom_power_w = max(0.0, max_charge_w - existing_precharge)
                if headroom_power_w <= 10.0:
                    continue

                # Max energy we can add in this step (input to battery)
                max_add_input_kwh = (headroom_power_w * dt_hours) / 1000.0
                # Stored in battery
                max_add_stored_kwh = max_add_input_kwh * eta_chg
                # Deliverable to load at peak
                max_deliverable_kwh = max_add_stored_kwh * eta_dis

                alloc_deliverable_kwh = min(energy_needed_kwh, max_deliverable_kwh)
                alloc_input_kwh = alloc_deliverable_kwh / eta_rt
                alloc_power_w = (alloc_input_kwh * 1000.0) / dt_hours

                grid_precharge_w[t_chg] += alloc_power_w
                energy_needed_kwh -= alloc_deliverable_kwh

                warnings.append(
                    f"Scheduled {alloc_power_w:.0f} W grid pre-charge at step {t_chg} "
                    f"(${buy_prices[t_chg]:.3f}/kWh) to avert peak import at step {t_peak} (${p_peak_buy:.3f}/kWh)."
                )

        return warnings

    @classmethod
    def _plan_export_arbitrage(
        cls,
        buy_prices: np.ndarray,
        sell_prices: np.ndarray,
        soc_curve: np.ndarray,
        capacity_kwh: float,
        min_soc: float,
        max_soc: float,
        max_charge_w: float,
        max_discharge_w: float,
        eta_rt: float,
        eta_chg: float,
        eta_dis: float,
        dt_hours: float,
        min_profit: float,
        deg_cost: float,
        total_steps: int,
        grid_precharge_w: np.ndarray,
        arbitrage_export_w: np.ndarray,
    ) -> List[str]:
        """
        Schedules dynamic wholesale feed-in export arbitrage.
        Finds pairs (t_chg, t_exp) where:
        Net Margin = (eta_rt * sell_price(t_exp)) - buy_price(t_chg) - deg_cost >= min_profit
        """
        warnings: List[str] = []

        # Find high export price candidate spikes
        export_candidates = np.where(sell_prices > 0.15)[0]
        if len(export_candidates) == 0:
            return warnings

        # Sort candidate export spikes by highest sell price
        sorted_exports = sorted(export_candidates, key=lambda t: sell_prices[t], reverse=True)

        for t_exp in sorted_exports:
            p_sell = sell_prices[t_exp]

            # Look for earlier charge step t_chg < t_exp meeting the hurdle rate
            candidate_charges = []
            for t_chg in range(0, t_exp):
                p_buy = buy_prices[t_chg]
                net_margin = (eta_rt * p_sell) - p_buy - deg_cost
                if net_margin >= min_profit:
                    candidate_charges.append((t_chg, net_margin, p_buy))

            if not candidate_charges:
                continue

            # Sort by highest margin
            candidate_charges.sort(key=lambda item: item[1], reverse=True)
            best_chg_step, margin, best_buy_price = candidate_charges[0]

            # Determine available volume for this arbitrage pair
            chg_headroom_w = max(0.0, max_charge_w - grid_precharge_w[best_chg_step])
            exp_headroom_w = max(0.0, max_discharge_w - arbitrage_export_w[t_exp])

            if chg_headroom_w < 100.0 or exp_headroom_w < 100.0:
                continue

            # Maximum power that can be traded
            trade_power_w = min(chg_headroom_w, exp_headroom_w / eta_rt)
            trade_energy_input_kwh = (trade_power_w * dt_hours) / 1000.0
            trade_energy_export_kwh = trade_energy_input_kwh * eta_rt
            export_power_w = (trade_energy_export_kwh * 1000.0) / dt_hours

            grid_precharge_w[best_chg_step] += trade_power_w
            arbitrage_export_w[t_exp] += export_power_w

            warnings.append(
                f"Export Arbitrage: Scheduled {trade_power_w:.0f} W grid charge at step {best_chg_step} "
                f"(${best_buy_price:.3f}/kWh) and {export_power_w:.0f} W export at step {t_exp} "
                f"(${p_sell:.3f}/kWh) with estimated net profit margin of ${margin:.3f}/kWh."
            )

        return warnings

    @classmethod
    def _simulate_forward(
        cls,
        net_load: np.ndarray,
        initial_soc: float,
        capacity_kwh: float,
        min_soc: float,
        max_soc: float,
        max_charge_w: float,
        max_discharge_w: float,
        eta_chg: float,
        eta_dis: float,
        dt_hours: float,
        grid_precharge_w: np.ndarray,
        arbitrage_export_w: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Fast forward simulation for pass 1 and pass 2 planning."""
        total_steps = len(net_load)
        soc = np.zeros(total_steps)
        grid_import = np.zeros(total_steps)
        grid_export = np.zeros(total_steps)

        current_soc = initial_soc

        for t in range(total_steps):
            soc[t] = current_soc
            current_energy_kwh = current_soc * capacity_kwh
            p_net = net_load[t]
            precharge_w = grid_precharge_w[t]
            arb_export_w = arbitrage_export_w[t]

            # 1. Grid Pre-Charge (charges battery from grid)
            if precharge_w > 0:
                headroom_kwh = max(0.0, (max_soc * capacity_kwh) - current_energy_kwh)
                chg_kwh = min((precharge_w * dt_hours) / 1000.0, headroom_kwh / eta_chg)
                current_energy_kwh += chg_kwh * eta_chg
                grid_import[t] += (chg_kwh * 1000.0) / dt_hours

            # 2. Solar Surplus (p_net < 0) or Home Deficit (p_net > 0)
            if p_net < 0:
                # Solar surplus
                surplus_w = -p_net
                headroom_kwh = max(0.0, (max_soc * capacity_kwh) - current_energy_kwh)
                max_chg_power = min(surplus_w, max_charge_w)
                chg_kwh = min((max_chg_power * dt_hours) / 1000.0, headroom_kwh / eta_chg)
                current_energy_kwh += chg_kwh * eta_chg
                grid_export[t] += max(0.0, surplus_w - (chg_kwh * 1000.0) / dt_hours)
            else:
                # Home deficit
                avail_dis_kwh = max(0.0, (current_energy_kwh - (min_soc * capacity_kwh))) * eta_dis
                max_dis_power = min(p_net, max_discharge_w)
                dis_kwh = min((max_dis_power * dt_hours) / 1000.0, avail_dis_kwh)
                current_energy_kwh -= (dis_kwh / eta_dis)
                grid_import[t] += max(0.0, p_net - (dis_kwh * 1000.0) / dt_hours)

            # 3. Arbitrage Export (discharges battery to grid)
            if arb_export_w > 0:
                avail_dis_kwh = max(0.0, (current_energy_kwh - (min_soc * capacity_kwh))) * eta_dis
                max_dis_power = min(arb_export_w, max_discharge_w)
                dis_kwh = min((max_dis_power * dt_hours) / 1000.0, avail_dis_kwh)
                current_energy_kwh -= (dis_kwh / eta_dis)
                grid_export[t] += (dis_kwh * 1000.0) / dt_hours

            current_soc = min(max_soc, max(min_soc, current_energy_kwh / capacity_kwh))

        return soc, grid_import, grid_export

    @classmethod
    def _simulate_final(
        cls,
        net_load: np.ndarray,
        initial_soc: float,
        capacity_kwh: float,
        min_soc: float,
        max_soc: float,
        max_charge_w: float,
        max_discharge_w: float,
        eta_chg: float,
        eta_dis: float,
        dt_hours: float,
        grid_precharge_w: np.ndarray,
        arbitrage_export_w: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Dict[str, float]]:
        """
        Final precision simulation producing full power curves and telemetry metrics.
        """
        total_steps = len(net_load)
        soc = np.zeros(total_steps)
        grid_import = np.zeros(total_steps)
        grid_export = np.zeros(total_steps)
        batt_power = np.zeros(total_steps)

        solar_charged_kwh = 0.0
        grid_precharged_kwh = 0.0
        home_discharged_kwh = 0.0
        arbitrage_exported_kwh = 0.0

        current_soc = initial_soc

        for t in range(total_steps):
            soc[t] = current_soc
            current_energy_kwh = current_soc * capacity_kwh
            p_net = net_load[t]
            precharge_w = grid_precharge_w[t]
            arb_export_w = arbitrage_export_w[t]

            step_batt_power = 0.0

            # 1. Grid Pre-Charge
            if precharge_w > 0:
                headroom_kwh = max(0.0, (max_soc * capacity_kwh) - current_energy_kwh)
                max_chg_power = min(precharge_w, max_charge_w)
                chg_kwh = min((max_chg_power * dt_hours) / 1000.0, headroom_kwh / eta_chg)
                actual_chg_w = (chg_kwh * 1000.0) / dt_hours
                current_energy_kwh += chg_kwh * eta_chg
                grid_import[t] += actual_chg_w
                step_batt_power += actual_chg_w
                grid_precharged_kwh += chg_kwh

            # 2. Solar Surplus or Home Deficit
            if p_net < 0:
                # Solar surplus
                surplus_w = -p_net
                remaining_chg_rate = max(0.0, max_charge_w - max(0.0, step_batt_power))
                headroom_kwh = max(0.0, (max_soc * capacity_kwh) - current_energy_kwh)
                max_solar_chg_w = min(surplus_w, remaining_chg_rate)
                chg_kwh = min((max_solar_chg_w * dt_hours) / 1000.0, headroom_kwh / eta_chg)
                actual_solar_chg_w = (chg_kwh * 1000.0) / dt_hours
                current_energy_kwh += chg_kwh * eta_chg
                grid_export[t] += max(0.0, surplus_w - actual_solar_chg_w)
                step_batt_power += actual_solar_chg_w
                solar_charged_kwh += chg_kwh
            else:
                # Home deficit
                avail_dis_kwh = max(0.0, (current_energy_kwh - (min_soc * capacity_kwh))) * eta_dis
                max_dis_power = min(p_net, max_discharge_w)
                dis_kwh = min((max_dis_power * dt_hours) / 1000.0, avail_dis_kwh)
                actual_dis_w = (dis_kwh * 1000.0) / dt_hours
                current_energy_kwh -= (dis_kwh / eta_dis)
                grid_import[t] += max(0.0, p_net - actual_dis_w)
                step_batt_power -= actual_dis_w
                home_discharged_kwh += dis_kwh

            # 3. Arbitrage Export
            if arb_export_w > 0:
                remaining_dis_rate = max(0.0, max_discharge_w - max(0.0, -step_batt_power))
                avail_dis_kwh = max(0.0, (current_energy_kwh - (min_soc * capacity_kwh))) * eta_dis
                max_arb_power = min(arb_export_w, remaining_dis_rate)
                dis_kwh = min((max_arb_power * dt_hours) / 1000.0, avail_dis_kwh)
                actual_arb_dis_w = (dis_kwh * 1000.0) / dt_hours
                current_energy_kwh -= (dis_kwh / eta_dis)
                grid_export[t] += actual_arb_dis_w
                step_batt_power -= actual_arb_dis_w
                arbitrage_exported_kwh += dis_kwh

            batt_power[t] = step_batt_power
            current_soc = min(max_soc, max(min_soc, current_energy_kwh / capacity_kwh))

        metrics = {
            "solar_charged_kwh": solar_charged_kwh,
            "grid_precharged_kwh": grid_precharged_kwh,
            "home_discharged_kwh": home_discharged_kwh,
            "arbitrage_exported_kwh": arbitrage_exported_kwh,
        }

        return soc, grid_import, grid_export, batt_power, metrics
