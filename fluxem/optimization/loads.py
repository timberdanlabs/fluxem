r"""
Flexible Deferrable Load Management Engine (Module B).
Implements continuous unbroken block scheduling, flexible multi-window cluster scheduling
with max-start constraints, priority-based solar stacking, and state-aware mid-cycle tracking.
r"""

from datetime import datetime, time, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import numpy as np
import pandas as pd

from fluxem.models.loads import DeferrableLoad
from fluxem.models.time_series import ProcessedTimeSeriesData
from fluxem.storage import config_store

logger = logging.getLogger("fluxem.optimization.loads")


class DeferrableLoadScheduler:
    r"""
    Schedules deferrable loads based on time-series pricing, solar forecasts,
    runtime constraints, and active mid-cycle operational states.
    r"""

    @classmethod
    def schedule_all(
        cls,
        loads: List[DeferrableLoad],
        time_series: ProcessedTimeSeriesData,
    ) -> Tuple[Dict[str, List[float]], List[float], List[str]]:
        r"""
        Schedules all deferrable loads ordered by priority.
        Returns:
        1. Dict mapping load_id -> scheduled power curve array (Watts)
        2. Total combined deferrable load power curve array (Watts)
        3. List of operational / scheduling warnings and notes
        r"""
        warnings: List[str] = []
        schedules: Dict[str, List[float]] = {}
        total_steps = time_series.total_steps
        combined_deferrable_power = [0.0] * total_steps

        if not loads or total_steps == 0:
            return schedules, combined_deferrable_power, warnings

        # Track remaining excess solar available for lower-priority loads
        excess_solar_available = np.maximum(
            0.0,
            np.array(time_series.solar_powers) - np.array(time_series.load_powers)
        ).tolist()

        # Sort loads by priority (highest priority first)
        sorted_loads = sorted(loads, key=lambda l: l.priority, reverse=True)

        for load in sorted_loads:
            load_schedule, load_warnings = cls.schedule_single_load(
                load=load,
                time_series=time_series,
                available_excess_solar=excess_solar_available,
            )
            schedules[load.id] = load_schedule
            warnings.extend(load_warnings)

            # Deduct scheduled load power from excess solar
            for t in range(total_steps):
                combined_deferrable_power[t] += load_schedule[t]
                excess_solar_available[t] = max(0.0, excess_solar_available[t] - load_schedule[t])

        return schedules, combined_deferrable_power, warnings

    @classmethod
    def _group_step_indices_by_day(
        cls,
        timestamps: List[datetime],
        ha_timezone: Optional[str] = None,
    ) -> List[List[int]]:
        r"""
        Groups sequential timestep indices into calendar days (Day 0, Day 1, Day 2...)
        using local calendar date boundaries.
        r"""
        if not timestamps:
            return []

        tz = None
        tz_str = ha_timezone or getattr(config_store.config, "ha_timezone", None)
        if tz_str and tz_str.lower() not in ("auto", "none", ""):
            try:
                tz = ZoneInfo(tz_str)
            except Exception:
                pass

        days_map: Dict[Any, List[int]] = {}
        for idx, ts in enumerate(timestamps):
            if ts.tzinfo is not None and tz is not None:
                local_dt = ts.astimezone(tz)
            elif ts.tzinfo is not None:
                local_dt = ts
            else:
                local_dt = ts

            local_date = local_dt.date()
            if local_date not in days_map:
                days_map[local_date] = []
            days_map[local_date].append(idx)

        return list(days_map.values())

    @classmethod
    def schedule_single_load(
        cls,
        load: DeferrableLoad,
        time_series: ProcessedTimeSeriesData,
        available_excess_solar: List[float],
    ) -> Tuple[List[float], List[str]]:
        r"""
        Schedules an individual deferrable load day-by-day across the full prediction horizon.
        - Day 0 (today): schedules remaining daily quota (required_hours - accumulated_hours_today).
        - Subsequent Days (tomorrow, etc.): schedules fresh full daily quota (required_hours).
        r"""
        warnings: List[str] = []
        total_steps = time_series.total_steps
        dt_hours = time_series.timestep_hours
        schedule = [0.0] * total_steps

        if total_steps == 0:
            return schedule, warnings

        # 1. Compute global time window mask and step costs
        valid_mask = cls._compute_time_window_mask(
            timestamps=time_series.timestamps,
            window_start=load.window_start_time,
            window_end=load.window_end_time,
        )

        step_costs = cls._compute_marginal_costs(
            load_power_w=load.nominal_power_w,
            buy_prices=time_series.buy_prices,
            sell_prices=time_series.sell_prices,
            available_excess_solar=available_excess_solar,
            dt_hours=dt_hours,
            valid_mask=valid_mask,
        )

        # 2. Group timesteps into calendar days
        day_groups = cls._group_step_indices_by_day(
            time_series.timestamps,
            ha_timezone=time_series.timezone_name,
        )

        for day_idx, day_indices in enumerate(day_groups):
            day_total_steps = len(day_indices)
            if day_total_steps == 0:
                continue

            # Determine runtime requirement for this specific day
            if day_idx == 0:
                remaining_hours = max(0.0, load.required_hours - load.accumulated_hours_today)
                is_running = load.is_running
                if remaining_hours <= 1e-5:
                    warnings.append(
                        f"Load '{load.id}' ({load.name}) already completed required runtime today "
                        f"({load.accumulated_hours_today:.1f}h / {load.required_hours:.1f}h)."
                    )
                    continue
            else:
                remaining_hours = load.required_hours
                is_running = False

            # Steps needed for this day
            steps_needed = int(math.ceil(remaining_hours / dt_hours))
            if steps_needed > day_total_steps:
                steps_needed = day_total_steps

            if steps_needed <= 0:
                continue

            # Check validity within this day
            day_valid_mask = [valid_mask[i] for i in day_indices]
            valid_in_day = [i for i, v in enumerate(day_valid_mask) if v]
            if not valid_in_day:
                warnings.append(
                    f"Load '{load.id}' has no valid timesteps on Day {day_idx + 1} within time window "
                    f"[{load.window_start_time} - {load.window_end_time}]."
                )
                continue

            if len(valid_in_day) < steps_needed:
                warnings.append(
                    f"Load '{load.id}' Day {day_idx + 1} time window contains only {len(valid_in_day)} valid steps, "
                    f"less than required {steps_needed} steps. Scheduling max possible in window."
                )
                steps_needed = len(valid_in_day)

            day_step_costs = [step_costs[i] for i in day_indices]

            # Build a temporary day load object to schedule within the day
            day_load = load.model_copy()
            day_load.is_running = is_running

            if load.continuous:
                chosen_rel, cont_warnings = cls._schedule_continuous_block(
                    load=day_load,
                    steps_needed=steps_needed,
                    step_costs=day_step_costs,
                    valid_mask=day_valid_mask,
                    total_steps=day_total_steps,
                )
                warnings.extend(cont_warnings)
            else:
                chosen_rel, flex_warnings = cls._schedule_flexible_clusters(
                    load=day_load,
                    steps_needed=steps_needed,
                    step_costs=day_step_costs,
                    valid_mask=day_valid_mask,
                    total_steps=day_total_steps,
                )
                warnings.extend(flex_warnings)

            # Map relative day indices to global schedule
            for rel_idx in chosen_rel:
                global_idx = day_indices[rel_idx]
                schedule[global_idx] = float(load.nominal_power_w)

        return schedule, warnings

    @classmethod
    def _compute_marginal_costs(
        cls,
        load_power_w: float,
        buy_prices: List[float],
        sell_prices: List[float],
        available_excess_solar: List[float],
        dt_hours: float,
        valid_mask: List[bool],
    ) -> List[float]:
        r"""
        Calculates the net opportunity cost ($) of running the load at each timestep.
        - Excess solar portion is valued at foregone feed-in tariff (sell_price).
        - Grid import portion is valued at grid import tariff (buy_price).
        - Invalid window steps receive a prohibitive cost penalty.
        r"""
        costs: List[float] = []
        for t in range(len(buy_prices)):
            if not valid_mask[t]:
                costs.append(1e9)  # Prohibitive cost
                continue

            solar_w = available_excess_solar[t]
            buy_p = buy_prices[t]
            sell_p = sell_prices[t]

            if solar_w >= load_power_w:
                # Fully powered by excess solar
                cost = (load_power_w / 1000.0) * sell_p * dt_hours
            elif solar_w > 0:
                # Partially solar, partially grid
                solar_part = (solar_w / 1000.0) * sell_p * dt_hours
                grid_part = ((load_power_w - solar_w) / 1000.0) * buy_p * dt_hours
                cost = solar_part + grid_part
            else:
                # Fully grid import
                cost = (load_power_w / 1000.0) * buy_p * dt_hours

            costs.append(cost)

        return costs

    @classmethod
    def _schedule_continuous_block(
        cls,
        load: DeferrableLoad,
        steps_needed: int,
        step_costs: List[float],
        valid_mask: List[bool],
        total_steps: int,
    ) -> Tuple[List[int], List[str]]:
        r"""
        Schedules an unbroken contiguous block.
        If is_running == True, preserves and completes the active mid-cycle block from step 0.
        Otherwise, finds the lowest cost contiguous block.
        r"""
        warnings: List[str] = []

        # Case A: Load is currently running mid-cycle
        if load.is_running:
            # Must continue uninterrupted from step 0
            end_idx = min(total_steps, steps_needed)
            chosen = list(range(0, end_idx))
            warnings.append(
                f"Continuous load '{load.id}' is actively running. Enforcing contiguous block "
                f"from step 0 for {len(chosen)} steps ({len(chosen) * 0.5:.1f}h) to preserve mid-cycle state."
            )
            return chosen, warnings

        # Case B: Find optimal start index for contiguous block
        best_start = -1
        min_block_cost = float("inf")

        for start_idx in range(0, total_steps - steps_needed + 1):
            block_indices = range(start_idx, start_idx + steps_needed)
            # Ensure all steps in block are valid
            if all(valid_mask[i] for i in block_indices):
                block_cost = sum(step_costs[i] for i in block_indices)
                if block_cost < min_block_cost:
                    min_block_cost = block_cost
                    best_start = start_idx

        if best_start != -1:
            chosen = list(range(best_start, best_start + steps_needed))
        else:
            # Fallback: if no fully contiguous block fits in valid window, pick longest contiguous valid stretch
            warnings.append(
                f"Continuous load '{load.id}' could not find fully valid contiguous window of length {steps_needed}. "
                f"Selecting best available contiguous candidate."
            )
            chosen = cls._fallback_best_contiguous(step_costs, valid_mask, steps_needed, total_steps)

        return chosen, warnings

    @classmethod
    def _schedule_flexible_clusters(
        cls,
        load: DeferrableLoad,
        steps_needed: int,
        step_costs: List[float],
        valid_mask: List[bool],
        total_steps: int,
    ) -> Tuple[List[int], List[str]]:
        r"""
        Schedules a flexible load across optimal price/solar points,
        optionally subject to max_starts_per_day limit.
        r"""
        warnings: List[str] = []
        max_starts = load.max_starts_per_day

        # Valid candidates
        valid_indices = [i for i, v in enumerate(valid_mask) if v]

        if not valid_indices:
            return [], warnings

        # If no start constraint or starts allowed >= steps_needed, pick cheapest individual steps
        if max_starts is None or max_starts >= steps_needed:
            # If load is running right now, prefer keeping step 0 if reasonable
            sorted_by_cost = sorted(valid_indices, key=lambda i: step_costs[i])
            chosen = sorted(sorted_by_cost[:steps_needed])
            return chosen, warnings

        # If max_starts is constrained (e.g. max 1, 2, or 3 starts):
        # Solve dynamic programming to find optimal clusters of total length steps_needed with <= max_starts
        chosen = cls._solve_constrained_starts_dp(
            step_costs=step_costs,
            valid_mask=valid_mask,
            steps_needed=steps_needed,
            max_starts=max_starts,
            is_running=load.is_running,
            total_steps=total_steps,
        )

        return chosen, warnings

    @classmethod
    def _solve_constrained_starts_dp(
        cls,
        step_costs: List[float],
        valid_mask: List[bool],
        steps_needed: int,
        max_starts: int,
        is_running: bool,
        total_steps: int,
    ) -> List[int]:
        r"""
        Finds optimal start-stop clusters of total size `steps_needed` with $\le \text{max\_starts}$ starts.
        Uses exact dynamic programming over candidate intervals.
        r"""
        # Build candidate segments [i, j] of lengths 1..steps_needed
        # Precompute cost for every contiguous segment
        cost_matrix: Dict[Tuple[int, int], float] = {}
        for i in range(total_steps):
            current_cost = 0.0
            is_valid = True
            for j in range(i, total_steps):
                if not valid_mask[j]:
                    is_valid = False
                    break
                current_cost += step_costs[j]
                cost_matrix[(i, j)] = current_cost

        # DP state: dp[k][i][s] = min cost to schedule s steps in range [0..i] using exactly k starts
        # Since horizon total_steps <= 96, we can solve directly using segment composition:
        # dp[k, s] -> (min_cost, list of segments)
        # Base case: 0 starts, 0 steps -> cost 0, segments []
        memo: Dict[Tuple[int, int, int], Tuple[float, List[Tuple[int, int]]]] = {}

        def solve_dp(start_idx: int, starts_left: int, steps_left: int) -> Tuple[float, List[Tuple[int, int]]]:
            if steps_left == 0:
                return 0.0, []
            if starts_left == 0 or start_idx >= total_steps:
                return float("inf"), []

            key = (start_idx, starts_left, steps_left)
            if key in memo:
                return memo[key]

            # Option 1: Skip start_idx (no segment starting here)
            best_cost, best_segments = solve_dp(start_idx + 1, starts_left, steps_left)

            # Option 2: Start a segment at start_idx with length L in [1..steps_left]
            for seg_len in range(1, steps_left + 1):
                end_idx = start_idx + seg_len - 1
                if end_idx >= total_steps:
                    break
                if (start_idx, end_idx) in cost_matrix:
                    seg_cost = cost_matrix[(start_idx, end_idx)]
                    sub_cost, sub_segs = solve_dp(end_idx + 1, starts_left - 1, steps_left - seg_len)
                    total_c = seg_cost + sub_cost
                    if total_c < best_cost:
                        best_cost = total_c
                        best_segments = [(start_idx, end_idx)] + sub_segs

            memo[key] = (best_cost, best_segments)
            return memo[key]

        _, segments = solve_dp(0, max_starts, steps_needed)

        # Collect step indices
        chosen_indices: List[int] = []
        for start_i, end_i in segments:
            chosen_indices.extend(range(start_i, end_i + 1))

        if len(chosen_indices) == steps_needed:
            return sorted(chosen_indices)

        # Fallback if DP couldn't satisfy constraint: pick cheapest valid
        valid_indices = [i for i, v in enumerate(valid_mask) if v]
        sorted_by_cost = sorted(valid_indices, key=lambda i: step_costs[i])
        return sorted(sorted_by_cost[:steps_needed])

    @classmethod
    def _fallback_best_contiguous(
        cls,
        step_costs: List[float],
        valid_mask: List[bool],
        steps_needed: int,
        total_steps: int,
    ) -> List[int]:
        r"""Fallback to find best contiguous stretch within valid mask.r"""
        best_indices: List[int] = []
        best_cost = float("inf")

        for start in range(total_steps):
            current_stretch = []
            for j in range(start, total_steps):
                if not valid_mask[j] or len(current_stretch) >= steps_needed:
                    break
                current_stretch.append(j)

            if len(current_stretch) > len(best_indices):
                best_indices = current_stretch
                best_cost = sum(step_costs[i] for i in current_stretch)
            elif len(current_stretch) == len(best_indices) and len(current_stretch) > 0:
                cost = sum(step_costs[i] for i in current_stretch)
                if cost < best_cost:
                    best_indices = current_stretch
                    best_cost = cost

        return best_indices

    @classmethod
    def _compute_time_window_mask(
        cls,
        timestamps: List[datetime],
        window_start: Optional[str],
        window_end: Optional[str],
    ) -> List[bool]:
        r"""
        Generates a boolean mask indicating whether each timestamp falls within the configured time window.
        Supports both 'HH:MM' time strings and ISO timestamps.
        r"""
        if not window_start and not window_end:
            return [True] * len(timestamps)

        parsed_start_time = cls._parse_time_str(window_start)
        parsed_end_time = cls._parse_time_str(window_end)

        mask: List[bool] = []
        for ts in timestamps:
            t = ts.time()

            if parsed_start_time and parsed_end_time:
                if parsed_start_time <= parsed_end_time:
                    # Normal window: e.g. 08:00 to 17:00
                    in_window = parsed_start_time <= t <= parsed_end_time
                else:
                    # Overnight window: e.g. 22:00 to 06:00
                    in_window = (t >= parsed_start_time) or (t <= parsed_end_time)
            elif parsed_start_time:
                in_window = t >= parsed_start_time
            elif parsed_end_time:
                in_window = t <= parsed_end_time
            else:
                in_window = True

            mask.append(in_window)

        return mask

    @classmethod
    def _parse_time_str(cls, time_str: Optional[str]) -> Optional[time]:
        if not time_str:
            return None
        time_str = time_str.strip()
        try:
            # Handle HH:MM or HH:MM:SS
            if ":" in time_str and len(time_str) <= 8:
                parts = [int(p) for p in time_str.split(":")]
                return time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)
            # Handle full ISO format
            dt = pd.to_datetime(time_str)
            return dt.time()
        except Exception:
            logger.warning(f"Could not parse window time string '{time_str}'. Ignoring constraint.")
            return None
