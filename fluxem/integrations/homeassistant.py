"""
Direct Home Assistant REST API Client.
Connects using Long-Lived Access Tokens to discover entities, fetch real-time sensor states,
query historical sensor logs, and automatically stitch multi-day & multi-array forecasts
(e.g., Solcast Today + Tomorrow + Day 3, Amber Electric, Tibber, Nordpool) over configurable horizons.
Handles all timezone offsets, normalizing UTC and offset timestamps into canonical timelines.
"""

import bisect
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
import numpy as np
from dateutil import parser as date_parser

from fluxem.models.loads import DeferrableLoad
from fluxem.models.payload import HomeAssistantPayload

logger = logging.getLogger("fluxem.integrations.homeassistant")


def _get_first_key(d: Dict[str, Any], keys: List[str]) -> Any:
    """Safely extracts the first matching non-None value from dictionary without boolean short-circuiting on 0 or 0.0."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _parse_utc_dt(ts_raw: Any, ha_timezone: Optional[str] = None, ceil_seconds: bool = False) -> Optional[datetime]:
    """
    Converts any timestamp format into a canonical UTC datetime.
    Rounds seconds to avoid sub-minute / 1-second gaps between consecutive intervals.
    """
    if ts_raw is None:
        return None
    try:
        if isinstance(ts_raw, datetime):
            dt = ts_raw
        else:
            s = str(ts_raw).strip()
            dt = date_parser.isoparse(s)

        if dt.tzinfo is None:
            tz = None
            if ha_timezone and ha_timezone.lower() not in ("auto", "none", ""):
                try:
                    tz = ZoneInfo(ha_timezone)
                except ZoneInfoNotFoundError:
                    pass
            if tz:
                dt = dt.replace(tzinfo=tz)
            else:
                dt = dt.replace(tzinfo=timezone.utc)

        utc_dt = dt.astimezone(timezone.utc)
        if ceil_seconds:
            if utc_dt.second > 0 or utc_dt.microsecond > 0:
                utc_dt = (utc_dt + timedelta(minutes=1)).replace(second=0, microsecond=0)
            else:
                utc_dt = utc_dt.replace(microsecond=0)
        else:
            utc_dt = utc_dt.replace(second=0, microsecond=0)
        return utc_dt
    except Exception as e:
        logger.debug(f"Failed to parse datetime '{ts_raw}': {e}")
        return None


def _normalize_to_utc_iso(ts_raw: Any, ha_timezone: Optional[str] = None) -> Optional[str]:
    """
    Converts any timestamp format (UTC 'Z', offset '+10:00', naive string, or datetime)
    into a canonical UTC ISO 8601 string: 'YYYY-MM-DDTHH:MM:SSZ'.
    """
    dt = _parse_utc_dt(ts_raw, ha_timezone=ha_timezone, ceil_seconds=False)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class HomeAssistantClient:
    """
    Client for interacting with Home Assistant REST API.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout_seconds: float = 12.0,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.access_token = access_token
        self.timeout = timeout_seconds

    @property
    def is_configured(self) -> bool:
        """Returns True if URL and token are populated."""
        return bool(self.base_url and self.access_token)

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def test_connection(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Tests connection to Home Assistant and retrieves system info including timezone.
        Returns: (success: bool, message: str, info_dict: Dict)
        """
        if not self.is_configured:
            return False, "Home Assistant URL or Long-Lived Access Token is missing.", {}

        url = f"{self.base_url}/api/config"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code == 200:
                    data = response.json()
                    tz = data.get("time_zone", "UTC")
                    logger.info(f"Successfully connected to Home Assistant: {data.get('location_name', 'Home')} (Timezone: {tz})")
                    return True, "Successfully connected to Home Assistant API!", data
                elif response.status_code == 401:
                    logger.warning("Home Assistant authentication failed (401 Unauthorized)")
                    return False, "Authentication failed. Invalid Long-Lived Access Token.", {}
                else:
                    # Fallback to root API endpoint
                    r2 = await client.get(f"{self.base_url}/api/", headers=self._get_headers())
                    if r2.status_code == 200:
                        return True, "Successfully connected to Home Assistant API!", r2.json()
                    return False, f"Home Assistant returned HTTP {response.status_code}: {response.text}", {}
        except httpx.ConnectError:
            logger.error(f"Could not connect to Home Assistant at {self.base_url}")
            return False, f"Could not connect to Home Assistant at {self.base_url}. Check host IP and port.", {}
        except Exception as e:
            logger.exception("Unexpected error testing Home Assistant connection")
            return False, f"Connection error: {str(e)}", {}

    async def fetch_ha_timezone(self) -> Optional[str]:
        """Fetches configured timezone from Home Assistant /api/config."""
        if not self.is_configured:
            return None
        url = f"{self.base_url}/api/config"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code == 200:
                    return response.json().get("time_zone")
        except Exception as e:
            logger.warning(f"Could not fetch HA timezone: {e}")
        return None

    async def fetch_entities(self, domain_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Fetches all available entities from Home Assistant for UI dropdown selection,
        with smart classification by device class, units, and forecast capabilities.
        """
        if not self.is_configured:
            return []

        url = f"{self.base_url}/api/states"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code == 200:
                    states = response.json()
                    filtered = []
                    domains = domain_filter or ["sensor", "switch", "binary_sensor", "input_number", "input_boolean", "climate", "water_heater", "fan"]
                    for state in states:
                        entity_id = state.get("entity_id", "")
                        domain = entity_id.split(".")[0]
                        if domain in domains:
                            attributes = state.get("attributes", {}) or {}
                            friendly_name = attributes.get("friendly_name", entity_id)
                            device_class = str(attributes.get("device_class") or "")
                            unit = str(attributes.get("unit_of_measurement") or "")
                            state_val = state.get("state")

                            # Check for forecast data tables
                            has_forecast = bool(
                                "detailedForecast" in attributes
                                or "detailedHourly" in attributes
                                or "forecasts" in attributes
                                or "pv_estimate" in attributes
                                or "wh_hours" in attributes
                                or "prices" in attributes
                                or "d1" in attributes
                                or "d2" in attributes
                                or "d3" in attributes
                            )

                            # Categorization tags
                            categories: List[str] = []
                            eid_l = entity_id.lower()
                            fname_l = str(friendly_name).lower()
                            dc_l = device_class.lower()
                            unit_l = unit.lower()

                            # 1. Solar forecast & PV sensors
                            if (
                                any(k in eid_l or k in fname_l for k in ["solcast", "forecast_solar", "pv_estimate", "solar_forecast", "pv_forecast", "sun_forecast"])
                                or (has_forecast and any(k in eid_l or k in fname_l for k in ["solar", "pv", "sun", "generation", "production"]))
                                or (dc_l in ["power", "energy"] and any(k in eid_l or k in fname_l for k in ["solar", "pv", "production", "generation"]))
                            ):
                                categories.append("solar")

                            # 2. Buy price / electricity tariff
                            is_sell = any(k in eid_l or k in fname_l for k in ["feed_in", "feedin", "export", "sell", "fit"])
                            if not is_sell and (
                                any(k in eid_l or k in fname_l for k in ["amber_general", "general_price", "general_forecast", "tibber", "nordpool", "octopus", "buy_price", "import_price", "electricity_price", "grid_price"])
                                or (dc_l in ["monetary", "price"])
                                or any(u in unit_l for u in ["/kwh", "/mwh", "c/kwh", "$/kwh", "aud/kwh", "eur/kwh", "gbp/kwh"])
                                or (has_forecast and any(k in eid_l or k in fname_l for k in ["price", "tariff", "rate"]))
                            ):
                                categories.append("buy_price")

                            # 3. Sell / feed-in price
                            if is_sell and (
                                any(k in eid_l or k in fname_l for k in ["feed_in", "feedin", "export_price", "sell_price", "fit_price", "solar_export", "solar_feed_in", "amber_feed_in", "amber_feedin"])
                                or (dc_l in ["monetary", "price"])
                                or any(u in unit_l for u in ["/kwh", "/mwh", "c/kwh", "$/kwh", "aud/kwh", "eur/kwh", "gbp/kwh"])
                                or has_forecast
                            ):
                                categories.append("sell_price")

                            # 4. Power & Energy Meters (Whole house & appliances)
                            if (
                                dc_l in ["power", "energy"]
                                or unit_l in ["w", "kw", "mw", "va", "kva", "wh", "kwh", "mwh"]
                                or any(k in eid_l or k in fname_l for k in ["power", "consumption", "grid", "meter", "load", "import", "house", "home", "watt"])
                            ):
                                categories.append("power")

                            # 5. Battery State of Charge
                            if (
                                dc_l == "battery"
                                or (unit_l == "%" and any(k in eid_l or k in fname_l for k in ["battery", "soc", "state_of_charge", "charge"]))
                                or any(k in eid_l for k in ["battery_soc", "battery_state_of_charge", "battery_level", "battery_percent"])
                            ):
                                categories.append("battery")

                            # 6. Switchable entities
                            if domain in ["switch", "input_boolean", "climate", "water_heater", "fan", "light"]:
                                categories.append("switch")

                            filtered.append({
                                "entity_id": entity_id,
                                "friendly_name": friendly_name,
                                "state": str(state_val) if state_val is not None else "",
                                "domain": domain,
                                "device_class": device_class,
                                "unit": unit,
                                "has_forecast": has_forecast,
                                "categories": categories,
                            })
                    return sorted(filtered, key=lambda x: x["friendly_name"].lower())
                else:
                    logger.warning(f"Failed to fetch entities: HTTP {response.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching entities from Home Assistant: {e}")
            return []

    async def fetch_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Fetches the current state and attributes for a specific entity."""
        if not self.is_configured or not entity_id:
            return None

        clean_id = entity_id.strip()
        url = f"{self.base_url}/api/states/{clean_id}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    logger.warning(f"Entity '{clean_id}' not found in Home Assistant")
                    return None
                else:
                    logger.warning(f"Error fetching state for '{clean_id}': HTTP {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Failed to fetch state for '{clean_id}': {e}")
            return None

    async def fetch_history(
        self,
        entity_id: str,
        days: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Fetches historical state records for an entity over the past N days.
        """
        if not self.is_configured or not entity_id:
            return []

        clean_id = entity_id.strip()
        start_time = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        url = f"{self.base_url}/api/history/period/{start_time}?filter_entity_id={clean_id}&significant_changes_only=0"

        try:
            async with httpx.AsyncClient(timeout=max(self.timeout, 20.0)) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                        return data[0]
                    return []
                else:
                    logger.warning(f"Failed to fetch history for '{clean_id}': HTTP {response.status_code}")
                    return []
        except Exception as e:
            logger.warning(f"Failed to fetch history for '{clean_id}': {e}")
            return []

    def generate_load_forecast_from_history(
        self,
        history_records: List[Dict[str, Any]],
        deferrable_histories: Optional[List[Tuple[List[Dict[str, Any]], float]]] = None,
        horizon_days: int = 1,
        timestep_minutes: int = 30,
        method: str = "moving_average",
        ha_timezone: Optional[str] = None,
        start_time: Optional[datetime] = None,
    ) -> Tuple[List[str], List[float]]:
        """
        Calculates a forward-looking baseline household load forecast based on historical sensor data.
        Decomposes and deducts historical deferrable load consumption so baseline load does not
        replicate previous appliance runs (e.g. hot water heater from earlier today).
        Accurately translates UTC history into local daily routines (morning/evening peaks) and projects forward.
        """
        if not history_records:
            return [], []

        horizon_days = max(1, min(horizon_days, 3))
        steps_per_day = 1440 // timestep_minutes
        total_steps = steps_per_day * horizon_days

        # Determine local timezone
        tz = None
        if ha_timezone and ha_timezone.lower() not in ("auto", "none", ""):
            try:
                tz = ZoneInfo(ha_timezone)
            except ZoneInfoNotFoundError:
                pass
        if tz is None:
            tz = timezone.utc

        # Pre-process deferrable load histories for fast bisect lookup
        parsed_deferrables: List[Tuple[List[datetime], List[float]]] = []
        if deferrable_histories:
            for recs, nominal_power in deferrable_histories:
                if not recs:
                    continue
                series: List[Tuple[datetime, float]] = []
                for r in recs:
                    ts_str = r.get("last_changed") or r.get("last_updated")
                    st = r.get("state")
                    if ts_str and st not in (None, "unknown", "unavailable", "None", ""):
                        dt = _parse_utc_dt(ts_str, ha_timezone=ha_timezone)
                        if dt:
                            try:
                                p_val = float(st)
                                series.append((dt, max(0.0, p_val)))
                            except (ValueError, TypeError):
                                is_on = str(st).lower() in ("on", "true", "1")
                                series.append((dt, nominal_power if is_on else 0.0))
                if series:
                    series.sort(key=lambda x: x[0])
                    times = [x[0] for x in series]
                    powers = [x[1] for x in series]
                    parsed_deferrables.append((times, powers))

        slot_values: Dict[int, List[float]] = defaultdict(list)

        for rec in history_records:
            st = rec.get("state")
            if st in ("unknown", "unavailable", "None", "", None):
                continue
            try:
                val = float(st)
                if val < 30.0 and val > 0.0:
                    val *= 1000.0
                ts_str = rec.get("last_updated") or rec.get("last_changed")
                if ts_str:
                    dt_utc = date_parser.isoparse(ts_str.replace("Z", "+00:00"))
                    if dt_utc.tzinfo is None:
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                    else:
                        dt_utc = dt_utc.astimezone(timezone.utc)

                    # Deduct any active deferrable load power at this historical timestamp
                    historical_deferrable_power = 0.0
                    for d_times, d_powers in parsed_deferrables:
                        idx = bisect.bisect_right(d_times, dt_utc) - 1
                        if idx >= 0:
                            historical_deferrable_power += d_powers[idx]

                    baseline_val = max(0.0, val - historical_deferrable_power)

                    local_dt = dt_utc.astimezone(tz)
                    minute_of_day = local_dt.hour * 60 + local_dt.minute
                    slot_index = (minute_of_day // timestep_minutes) % steps_per_day
                    slot_values[slot_index].append(baseline_val)
            except (ValueError, TypeError):
                continue

        daily_profile = np.zeros(steps_per_day)

        for slot in range(steps_per_day):
            vals = slot_values.get(slot, [])
            if vals:
                if method == "median_profile":
                    daily_profile[slot] = float(np.median(vals))
                else:
                    daily_profile[slot] = float(np.mean(vals))
            else:
                hour = (slot * timestep_minutes) // 60
                if 6 <= hour <= 9 or 17 <= hour <= 22:
                    daily_profile[slot] = 900.0
                elif 0 <= hour <= 5:
                    daily_profile[slot] = 350.0
                else:
                    daily_profile[slot] = 500.0

        smoothed_daily = np.convolve(daily_profile, np.ones(3) / 3.0, mode="same")

        # Anchor start_time to current 30-min block in UTC
        if start_time is not None:
            start_utc = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
        else:
            now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            now_minute = (now_utc.minute // timestep_minutes) * timestep_minutes
            start_utc = now_utc.replace(minute=now_minute)

        timestamps = []
        load_powers = []

        for step in range(total_steps):
            step_utc = start_utc + timedelta(minutes=step * timestep_minutes)
            step_local = step_utc.astimezone(tz)
            minute_of_day = step_local.hour * 60 + step_local.minute
            slot_idx = (minute_of_day // timestep_minutes) % steps_per_day

            timestamps.append(step_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
            load_powers.append(round(float(smoothed_daily[slot_idx]), 1))

        return timestamps, load_powers

    async def calculate_load_accumulated_hours(
        self,
        entity_id: str,
        ha_timezone: Optional[str] = None,
        now_utc: Optional[datetime] = None,
    ) -> Tuple[float, bool]:
        """
        Queries Home Assistant history for an appliance switch or power sensor since local midnight,
        calculating total operating hours accumulated today and detecting if a heating/run cycle completed.
        Returns: (accumulated_hours: float, is_cycle_completed: bool)
        """
        if not entity_id:
            return 0.0, False

        tz = ZoneInfo("UTC")
        if ha_timezone and ha_timezone.lower() not in ("auto", "none", ""):
            try:
                tz = ZoneInfo(ha_timezone)
            except ZoneInfoNotFoundError:
                pass

        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)

        local_now = now_utc.astimezone(tz)
        local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc = local_midnight.astimezone(timezone.utc)

        # Fetch history records for the past 1 day
        history_records = await self.fetch_history(entity_id, days=1)
        if not history_records:
            return 0.0, False

        parsed: List[Tuple[datetime, str]] = []
        for r in history_records:
            ts_str = r.get("last_changed") or r.get("last_updated")
            st = r.get("state")
            if ts_str and st not in (None, "unknown", "unavailable", ""):
                dt = _parse_utc_dt(ts_str, ha_timezone=ha_timezone)
                if dt:
                    parsed.append((dt, str(st)))

        if not parsed:
            return 0.0, False

        parsed.sort(key=lambda x: x[0])

        total_active_seconds = 0.0
        last_was_active = False

        for i in range(len(parsed)):
            dt_start, st = parsed[i]
            dt_end = parsed[i + 1][0] if i + 1 < len(parsed) else now_utc

            seg_start = max(midnight_utc, dt_start)
            seg_end = min(now_utc, dt_end)

            if seg_end > seg_start:
                is_active = False
                if st.lower() in ("on", "true", "1"):
                    is_active = True
                else:
                    try:
                        if float(st) > 15.0:
                            is_active = True
                    except (ValueError, TypeError):
                        pass

                if is_active:
                    total_active_seconds += (seg_end - seg_start).total_seconds()
                    last_was_active = True
                else:
                    last_was_active = False

        accumulated_hours = round(total_active_seconds / 3600.0, 2)
        # Cycle is completed if it accumulated at least 15 mins (0.25h) today and is currently idle
        is_cycle_completed = bool(accumulated_hours >= 0.25 and not last_was_active)

        logger.info(
            f"Calculated {accumulated_hours:.2f}h accumulated runtime today for entity '{entity_id}' "
            f"(since local midnight {local_midnight.strftime('%Y-%m-%d %H:%M %Z')}, cycle_completed: {is_cycle_completed})."
        )
        return accumulated_hours, is_cycle_completed

    def _extract_solar_intervals(
        self,
        state_obj: Dict[str, Any],
        ha_timezone: Optional[str] = None,
    ) -> List[Tuple[datetime, datetime, float]]:
        """
        Parses Solcast, Forecast.Solar, Open-Meteo, or generic solar forecast attributes
        into UTC datetime intervals [start_dt, end_dt, pv_watts].
        """
        attrs = state_obj.get("attributes", {}) or {}
        intervals: List[Tuple[datetime, datetime, float]] = []

        # 1. Check list containers: detailedForecast, detailedHourly, forecast_today, forecast_tomorrow, forecasts
        for list_key in ("detailedForecast", "detailedHourly", "forecast_today", "forecast_tomorrow", "forecasts"):
            if list_key in attrs and isinstance(attrs[list_key], list):
                for entry in attrs[list_key]:
                    st = _parse_utc_dt(
                        _get_first_key(entry, ["period_start", "start_time", "time", "start"]),
                        ha_timezone=ha_timezone,
                        ceil_seconds=False,
                    )
                    et = _parse_utc_dt(
                        _get_first_key(entry, ["period_end", "end_time", "end"]),
                        ha_timezone=ha_timezone,
                        ceil_seconds=True,
                    )
                    if st and not et:
                        dur = _get_first_key(entry, ["duration", "interval_minutes"]) or 30
                        et = st + timedelta(minutes=int(dur))
                    pv = _get_first_key(entry, ["pv_estimate", "pv_estimate50", "pv_forecast", "pv_power", "power", "value"])
                    if st and et and pv is not None:
                        val = float(pv)
                        if 0.0 < val < 50.0:
                            val *= 1000.0
                        intervals.append((st, et, max(0.0, val)))
                if intervals:
                    intervals.sort(key=lambda x: x[0])
                    return intervals

        # 2. Check dict containers: energy_production_today, watts, detailed_forecast
        for key in ("energy_production_today", "watts", "detailed_forecast"):
            if key in attrs and isinstance(attrs[key], dict):
                for ts_str, val in attrs[key].items():
                    st = _parse_utc_dt(ts_str, ha_timezone=ha_timezone, ceil_seconds=False)
                    if st and val is not None:
                        et = st + timedelta(minutes=30)
                        intervals.append((st, et, max(0.0, float(val))))
                if intervals:
                    intervals.sort(key=lambda x: x[0])
                    return intervals

        return intervals

    def _extract_pricing_intervals(
        self,
        state_obj: Dict[str, Any],
        price_type: str = "buy",
        ha_timezone: Optional[str] = None,
    ) -> List[Tuple[datetime, datetime, float]]:
        """
        Parses Amber Electric, Amber Express, Tibber, Nordpool, or Octopus pricing forecast attributes
        into UTC datetime intervals [start_dt, end_dt, price_dollars_per_kwh].
        """
        attrs = state_obj.get("attributes", {}) or {}
        intervals: List[Tuple[datetime, datetime, float]] = []

        # 1. Check detailedForecast (Amber Express)
        if "detailedForecast" in attrs and isinstance(attrs["detailedForecast"], list):
            for entry in attrs["detailedForecast"]:
                st = _parse_utc_dt(
                    _get_first_key(entry, ["start_time", "time", "period_start", "start"]),
                    ha_timezone=ha_timezone,
                    ceil_seconds=False,
                )
                et = _parse_utc_dt(
                    _get_first_key(entry, ["end_time", "period_end", "end"]),
                    ha_timezone=ha_timezone,
                    ceil_seconds=True,
                )
                if st and not et:
                    dur = _get_first_key(entry, ["duration", "interval_minutes"]) or 30
                    et = st + timedelta(minutes=int(dur))
                p = _get_first_key(entry, ["per_kwh", "price", "value", "advanced_price", "total"])
                if p is None and isinstance(entry.get("advanced_price_predicted"), dict):
                    p = entry["advanced_price_predicted"].get("predicted") or entry["advanced_price_predicted"].get("value")
                if st and et and p is not None:
                    val = float(p)
                    if val > 2.0:
                        val /= 100.0
                    intervals.append((st, et, val))
            if intervals:
                intervals.sort(key=lambda x: x[0])
                return intervals

        # 2. Check forecasts (Official Amber Electric)
        if "forecasts" in attrs and isinstance(attrs["forecasts"], list):
            for entry in attrs["forecasts"]:
                st = _parse_utc_dt(
                    _get_first_key(entry, ["start_time", "start", "period_start", "time"]),
                    ha_timezone=ha_timezone,
                    ceil_seconds=False,
                )
                et = _parse_utc_dt(
                    _get_first_key(entry, ["end_time", "period_end", "end"]),
                    ha_timezone=ha_timezone,
                    ceil_seconds=True,
                )
                if st and not et:
                    dur = _get_first_key(entry, ["duration", "interval_minutes"]) or 30
                    et = st + timedelta(minutes=int(dur))
                p = _get_first_key(entry, ["per_kwh", "price", "value", "advanced_price", "total"])
                if st and et and p is not None:
                    val = float(p)
                    if val > 2.0:
                        val /= 100.0
                    intervals.append((st, et, val))
            if intervals:
                intervals.sort(key=lambda x: x[0])
                return intervals

        # 3. Check forecast (singular)
        if "forecast" in attrs and isinstance(attrs["forecast"], list):
            for entry in attrs["forecast"]:
                st = _parse_utc_dt(
                    _get_first_key(entry, ["time", "start_time", "start"]),
                    ha_timezone=ha_timezone,
                    ceil_seconds=False,
                )
                if st:
                    et = st + timedelta(minutes=30)
                    p = _get_first_key(entry, ["value", "per_kwh", "price"])
                    if p is not None:
                        val = float(p)
                        if val > 2.0:
                            val /= 100.0
                        intervals.append((st, et, val))
            if intervals:
                intervals.sort(key=lambda x: x[0])
                return intervals

        # 4. Check today / tomorrow / raw_today (Tibber, Nordpool)
        combined_records = []
        for key in ("today", "tomorrow", "raw_today", "raw_tomorrow"):
            if key in attrs and isinstance(attrs[key], list):
                combined_records.extend(attrs[key])

        if combined_records:
            for entry in combined_records:
                st = _parse_utc_dt(
                    _get_first_key(entry, ["startsAt", "start", "time"]),
                    ha_timezone=ha_timezone,
                    ceil_seconds=False,
                )
                if st:
                    et = st + timedelta(hours=1)
                    p = _get_first_key(entry, ["total", "price", "value"])
                    if p is not None:
                        val = float(p)
                        if val > 2.0:
                            val /= 100.0
                        intervals.append((st, et, val))
            if intervals:
                intervals.sort(key=lambda x: x[0])
                return intervals

        # 5. Check prices / price_forecast
        for key in ("prices", "price_forecast"):
            if key in attrs and isinstance(attrs[key], list):
                now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                for i, x in enumerate(attrs[key]):
                    if x is not None:
                        st = now_utc + timedelta(minutes=30 * i)
                        et = st + timedelta(minutes=30)
                        val = float(x)
                        if val > 2.0:
                            val /= 100.0
                        intervals.append((st, et, val))
                if intervals:
                    intervals.sort(key=lambda x: x[0])
                    return intervals

        return intervals

    def _extract_solar_forecast(
        self,
        state_obj: Dict[str, Any],
        ha_timezone: Optional[str] = None,
    ) -> Tuple[List[str], List[float]]:
        """Parses solar forecast into ISO timestamps and values."""
        intervals = self._extract_solar_intervals(state_obj, ha_timezone=ha_timezone)
        ts_list = [st.strftime("%Y-%m-%dT%H:%M:%SZ") for st, _, _ in intervals]
        val_list = [val for _, _, val in intervals]
        return ts_list, val_list

    def _extract_pricing_forecast(
        self,
        state_obj: Dict[str, Any],
        price_type: str = "buy",
        ha_timezone: Optional[str] = None,
    ) -> Tuple[List[str], List[float]]:
        """Parses pricing forecast into ISO timestamps and values."""
        intervals = self._extract_pricing_intervals(state_obj, price_type=price_type, ha_timezone=ha_timezone)
        ts_list = [st.strftime("%Y-%m-%dT%H:%M:%SZ") for st, _, _ in intervals]
        price_list = [p for _, _, p in intervals]
        return ts_list, price_list

    def _extract_load_forecast(
        self,
        state_obj: Dict[str, Any],
        ha_timezone: Optional[str] = None,
    ) -> Tuple[List[str], List[float]]:
        """Parses home load forecast attributes."""
        attrs = state_obj.get("attributes", {}) or {}
        timestamps: List[str] = []
        values: List[float] = []

        if "forecasts" in attrs and isinstance(attrs["forecasts"], list):
            for entry in attrs["forecasts"]:
                if isinstance(entry, dict):
                    ts = _get_first_key(entry, ["time", "timestamp", "start_time", "start"])
                    val = _get_first_key(entry, ["power", "load", "value"])
                    if ts:
                        norm_ts = _normalize_to_utc_iso(ts, ha_timezone=ha_timezone)
                        if norm_ts:
                            timestamps.append(norm_ts)
                    if val is not None:
                        values.append(float(val))
                elif isinstance(entry, (int, float)):
                    values.append(float(entry))

        return timestamps, values

    async def fetch_and_stitch_solar_forecast(
        self,
        solar_entity_input: str,
        horizon_days: int = 1,
        ha_timezone: Optional[str] = None,
    ) -> Tuple[List[str], List[float]]:
        """
        Intelligently fetches and stitches solar forecast entities into canonical UTC ISO timestamps.
        Supports multi-day sensors, multi-array summing, and auto-sibling discovery.
        """
        if not solar_entity_input:
            return [], []

        entity_ids = [e.strip() for e in re.split(r"[,;\n]+", solar_entity_input) if e.strip()]

        if len(entity_ids) == 1:
            base_id = entity_ids[0]
            discovered = [base_id]

            tomorrow_patterns = [
                ("_today", "_tomorrow"),
                ("_forecast_today", "_forecast_tomorrow"),
                ("_day_1", "_day_2"),
                ("_d1", "_d2"),
            ]
            for pattern_today, pattern_tomorrow in tomorrow_patterns:
                if pattern_today in base_id:
                    candidate = base_id.replace(pattern_today, pattern_tomorrow)
                    if candidate != base_id and candidate not in discovered:
                        discovered.append(candidate)
                        break

            if horizon_days >= 2:
                day3_patterns = [
                    ("_today", "_day_3"),
                    ("_today", "_d3"),
                    ("_forecast_today", "_forecast_day_3"),
                    ("_forecast_today", "_forecast_d3"),
                    ("_forecast_today", "_forecast_day_after_tomorrow"),
                    ("_day_1", "_day_3"),
                    ("_d1", "_d3"),
                ]
                for pattern_today, pattern_d3 in day3_patterns:
                    if pattern_today in base_id:
                        candidate = base_id.replace(pattern_today, pattern_d3)
                        if candidate not in discovered:
                            discovered.append(candidate)
                            break

            entity_ids = discovered

        timestamp_map: Dict[str, float] = defaultdict(float)

        for eid in entity_ids:
            state_obj = await self.fetch_state(eid)
            if not state_obj:
                continue
            ts_list, val_list = self._extract_solar_forecast(state_obj, ha_timezone=ha_timezone)
            for ts, val in zip(ts_list, val_list):
                timestamp_map[ts] += val

        if not timestamp_map:
            return [], []

        sorted_timestamps = sorted(timestamp_map.keys())
        sorted_values = [round(timestamp_map[ts], 1) for ts in sorted_timestamps]

        logger.info(f"Stitched {len(entity_ids)} solar sensor(s) into a {len(sorted_values)}-step curve.")
        return sorted_timestamps, sorted_values

    async def fetch_and_stitch_pricing_forecast(
        self,
        price_entity_input: str,
        price_type: str = "buy",
        ha_timezone: Optional[str] = None,
    ) -> Tuple[List[str], List[float]]:
        """
        Fetches and stitches pricing forecast entities into canonical UTC ISO timestamps.
        """
        if not price_entity_input:
            return [], []

        entity_ids = [e.strip() for e in re.split(r"[,;\n]+", price_entity_input) if e.strip()]
        timestamp_map: Dict[str, float] = {}

        for eid in entity_ids:
            state_obj = await self.fetch_state(eid)
            if not state_obj:
                continue
            ts_list, val_list = self._extract_pricing_forecast(state_obj, price_type=price_type, ha_timezone=ha_timezone)
            for ts, val in zip(ts_list, val_list):
                timestamp_map[ts] = val

        if not timestamp_map:
            return [], []

        sorted_timestamps = sorted(timestamp_map.keys())
        sorted_prices = [round(timestamp_map[ts], 4) for ts in sorted_timestamps]
        logger.info(f"Stitched {len(entity_ids)} {price_type} pricing sensor(s) into a {len(sorted_prices)}-step curve.")
        return sorted_timestamps, sorted_prices

    async def build_payload_from_entities(
        self,
        mappings: Dict[str, str],
        configured_loads: Optional[List[DeferrableLoad]] = None,
        prediction_horizon_days: int = 1,
        load_history_days: int = 3,
        load_forecast_method: str = "moving_average",
        ha_timezone: Optional[str] = "auto",
        start_time: Optional[datetime] = None,
        force_reoptimize: bool = True,
    ) -> HomeAssistantPayload:
        """
        Pulls live sensor states, history, and forecast attributes directly from Home Assistant
        and constructs a complete, valid HomeAssistantPayload over the configured horizon (1 to 3 days).
        Aligns all multi-sensor time-series to unified canonical UTC timestamps starting from the current timestep.
        """
        horizon_days = max(1, min(prediction_horizon_days, 3))
        timestep_minutes = 30
        steps_per_day = 1440 // timestep_minutes
        target_steps = steps_per_day * horizon_days

        # Auto-detect HA timezone if 'auto'
        resolved_tz = ha_timezone
        if resolved_tz in (None, "", "auto"):
            ha_cfg_tz = await self.fetch_ha_timezone()
            if ha_cfg_tz:
                resolved_tz = ha_cfg_tz
                logger.info(f"Auto-detected Home Assistant timezone: {resolved_tz}")

        # Determine canonical start time (current time floored to timestep)
        if start_time is not None:
            start_utc = _parse_utc_dt(start_time, ha_timezone=resolved_tz) or datetime.now(timezone.utc).replace(second=0, microsecond=0)
        else:
            now_utc = datetime.now(timezone.utc)
            now_minute = (now_utc.minute // timestep_minutes) * timestep_minutes
            start_utc = now_utc.replace(minute=now_minute, second=0, microsecond=0)

        # Generate target timestamp sequence
        target_dt_list = [start_utc + timedelta(minutes=step * timestep_minutes) for step in range(target_steps)]
        timestamps = [dt.strftime("%Y-%m-%dT%H:%M:%SZ") for dt in target_dt_list]

        actual_solar_power: Optional[float] = None
        actual_house_power: Optional[float] = None
        actual_buy_price: Optional[float] = None
        actual_sell_price: Optional[float] = None
        battery_soc: Optional[float] = None

        logger.info(
            f"Starting Home Assistant sensor sync (Start: {timestamps[0]}, Steps: {target_steps}, "
            f"Horizon: {horizon_days}d, History: {load_history_days}d, TZ: {resolved_tz})..."
        )

        # --- 1. Solar Forecast: Collect all intervals & align onto target grid ---
        solar_input = mappings.get("solar_forecast_entity", "")
        solar_intervals: List[Tuple[datetime, datetime, float]] = []
        if solar_input:
            entity_ids = [e.strip() for e in re.split(r"[,;\n]+", solar_input) if e.strip()]
            if len(entity_ids) == 1:
                base_id = entity_ids[0]
                discovered = [base_id]
                tomorrow_patterns = [
                    ("_today", "_tomorrow"),
                    ("_forecast_today", "_forecast_tomorrow"),
                    ("_day_1", "_day_2"),
                    ("_d1", "_d2"),
                ]
                for pattern_today, pattern_tomorrow in tomorrow_patterns:
                    if pattern_today in base_id:
                        cand = base_id.replace(pattern_today, pattern_tomorrow)
                        if cand != base_id and cand not in discovered:
                            discovered.append(cand)
                            break
                if horizon_days >= 2:
                    for pattern_today, pattern_d3 in [("_today", "_day_3"), ("_today", "_d3"), ("_forecast_today", "_forecast_day_3"), ("_day_1", "_day_3")]:
                        if pattern_today in base_id:
                            cand = base_id.replace(pattern_today, pattern_d3)
                            if cand not in discovered:
                                discovered.append(cand)
                                break
                entity_ids = discovered

            for eid in entity_ids:
                s_obj = await self.fetch_state(eid)
                if s_obj:
                    ints = self._extract_solar_intervals(s_obj, ha_timezone=resolved_tz)
                    solar_intervals.extend(ints)

        solar_intervals.sort(key=lambda x: x[0])

        solar_forecast: List[float] = []
        for t in target_dt_list:
            matched = [pv for st, et, pv in solar_intervals if st <= t < et]
            if matched:
                solar_forecast.append(round(sum(matched), 1))
            else:
                # If within 15 min of a discrete point
                close_pts = [pv for st, _, pv in solar_intervals if abs((st - t).total_seconds()) <= 900]
                if close_pts:
                    solar_forecast.append(round(sum(close_pts), 1))
                else:
                    solar_forecast.append(0.0)

        # --- 2. Buy Price Forecast: Collect intervals & align with forward-fill ---
        buy_price_input = mappings.get("buy_price_forecast_entity", "")
        buy_intervals: List[Tuple[datetime, datetime, float]] = []
        buy_state_val: Optional[float] = None
        if buy_price_input:
            entity_ids = [e.strip() for e in re.split(r"[,;\n]+", buy_price_input) if e.strip()]
            for eid in entity_ids:
                s_obj = await self.fetch_state(eid)
                if s_obj:
                    buy_state_val = self._parse_float_state(s_obj)
                    if buy_state_val is not None and buy_state_val > 2.0:
                        buy_state_val /= 100.0
                    ints = self._extract_pricing_intervals(s_obj, price_type="buy", ha_timezone=resolved_tz)
                    buy_intervals.extend(ints)

        buy_intervals.sort(key=lambda x: x[0])

        # Scalar buy price sensor (if mapped)
        if mappings.get("buy_price_entity"):
            s = await self.fetch_state(mappings["buy_price_entity"])
            actual_buy_price = self._parse_float_state(s)
            if actual_buy_price is not None and actual_buy_price > 2.0:
                actual_buy_price /= 100.0
        elif buy_state_val is not None:
            actual_buy_price = buy_state_val

        default_buy = actual_buy_price if actual_buy_price is not None else 0.25

        buy_prices: List[float] = []
        for t in target_dt_list:
            matched = [p for st, et, p in buy_intervals if st <= t < et]
            if matched:
                buy_prices.append(round(matched[0], 4))
            elif buy_intervals and t >= buy_intervals[-1][1]:
                buy_prices.append(round(buy_intervals[-1][2], 4))
            elif buy_intervals and t < buy_intervals[0][0]:
                buy_prices.append(round(buy_intervals[0][2], 4))
            else:
                buy_prices.append(round(default_buy, 4))

        # --- 3. Sell Price Forecast: Collect intervals & align with forward-fill ---
        sell_price_input = mappings.get("sell_price_forecast_entity", "")
        sell_intervals: List[Tuple[datetime, datetime, float]] = []
        sell_state_val: Optional[float] = None
        if sell_price_input:
            entity_ids = [e.strip() for e in re.split(r"[,;\n]+", sell_price_input) if e.strip()]
            for eid in entity_ids:
                s_obj = await self.fetch_state(eid)
                if s_obj:
                    sell_state_val = self._parse_float_state(s_obj)
                    if sell_state_val is not None and sell_state_val > 2.0:
                        sell_state_val /= 100.0
                    ints = self._extract_pricing_intervals(s_obj, price_type="sell", ha_timezone=resolved_tz)
                    sell_intervals.extend(ints)

        sell_intervals.sort(key=lambda x: x[0])

        if mappings.get("sell_price_entity"):
            s = await self.fetch_state(mappings["sell_price_entity"])
            actual_sell_price = self._parse_float_state(s)
            if actual_sell_price is not None and actual_sell_price > 2.0:
                actual_sell_price /= 100.0
        elif sell_state_val is not None:
            actual_sell_price = sell_state_val

        default_sell = actual_sell_price if actual_sell_price is not None else 0.04

        sell_prices: List[float] = []
        for t in target_dt_list:
            matched = [p for st, et, p in sell_intervals if st <= t < et]
            if matched:
                sell_prices.append(round(matched[0], 4))
            elif sell_intervals and t >= sell_intervals[-1][1]:
                sell_prices.append(round(sell_intervals[-1][2], 4))
            elif sell_intervals and t < sell_intervals[0][0]:
                sell_prices.append(round(sell_intervals[0][2], 4))
            else:
                sell_prices.append(round(default_sell, 4))

        # --- 4. Fetch Real-time Scalar Sensors ---
        if mappings.get("house_power_entity"):
            s = await self.fetch_state(mappings["house_power_entity"])
            actual_house_power = self._parse_float_state(s)
            if actual_house_power is not None:
                logger.info(f"Read real-time house_power: {actual_house_power} W")

        if mappings.get("solar_power_entity"):
            s = await self.fetch_state(mappings["solar_power_entity"])
            actual_solar_power = self._parse_float_state(s)

        if mappings.get("battery_soc_entity"):
            s = await self.fetch_state(mappings["battery_soc_entity"])
            battery_soc = self._parse_float_state(s)
            if battery_soc is not None:
                logger.info(f"Read battery SOC: {battery_soc}%")

        # --- 5. Household Baseline Load Forecast ---
        load_forecast: List[float] = []
        load_entity = mappings.get("load_forecast_entity")
        if load_entity:
            s_obj = await self.fetch_state(load_entity)
            if s_obj:
                _, raw_loads = self._extract_load_forecast(s_obj, ha_timezone=resolved_tz)
                if raw_loads:
                    load_forecast = (raw_loads + [raw_loads[-1]] * target_steps)[:target_steps]

        if not load_forecast and mappings.get("house_power_entity"):
            history_records = await self.fetch_history(mappings["house_power_entity"], days=load_history_days)
            if history_records:
                # Fetch history for configured deferrable loads that are included in total load
                deferrable_histories = []
                if configured_loads:
                    for l in configured_loads:
                        if getattr(l, "is_included_in_total_load", True):
                            hist_eid = l.power_sensor_entity_id or l.switch_entity_id or mappings.get(f"load_{l.id}_power_entity") or mappings.get(f"load_{l.id}_switch_entity")
                            if hist_eid:
                                d_recs = await self.fetch_history(hist_eid, days=load_history_days)
                                if d_recs:
                                    deferrable_histories.append((d_recs, float(l.nominal_power_w)))

                _, hist_loads = self.generate_load_forecast_from_history(
                    history_records=history_records,
                    deferrable_histories=deferrable_histories,
                    horizon_days=horizon_days,
                    timestep_minutes=timestep_minutes,
                    method=load_forecast_method,
                    ha_timezone=resolved_tz,
                    start_time=start_utc,
                )
                load_forecast = hist_loads
                logger.info(
                    f"Generated {len(load_forecast)}-step home load forecast from past {load_history_days} days history "
                    f"(decomposed {len(deferrable_histories)} deferrable load(s))."
                )

        if not load_forecast:
            base_load = actual_house_power if actual_house_power is not None else 500.0
            load_forecast = [base_load] * target_steps

        # Ensure lengths match target_steps exactly
        solar_forecast = (solar_forecast + [0.0] * target_steps)[:target_steps]
        buy_prices = (buy_prices + [default_buy] * target_steps)[:target_steps]
        sell_prices = (sell_prices + [default_sell] * target_steps)[:target_steps]
        load_forecast = (load_forecast + [500.0] * target_steps)[:target_steps]

        # --- 6. Fetch live state & history for configured deferrable loads ---
        updated_loads = []
        if configured_loads:
            for load in configured_loads:
                load_copy = load.model_copy()
                power_entity = load.power_sensor_entity_id or mappings.get(f"load_{load.id}_power_entity")
                if power_entity:
                    s = await self.fetch_state(power_entity)
                    measured_power = self._parse_float_state(s)
                    if measured_power is not None:
                        load_copy.current_power_w = measured_power
                        if measured_power > 10.0:
                            load_copy.is_running = True
                            logger.info(f"Load '{load.name or load.id}' measured power: {measured_power} W (Active ON)")

                switch_entity = load.switch_entity_id or mappings.get(f"load_{load.id}_switch_entity")
                if switch_entity:
                    s = await self.fetch_state(switch_entity)
                    if s and s.get("state") in ("on", "true", "1"):
                        load_copy.is_running = True
                        logger.info(f"Load '{load.name or load.id}' switch is ON")
                    elif s and s.get("state") in ("off", "false", "0"):
                        load_copy.is_running = False

                # Auto-calculate accumulated runtime today from history
                hist_entity = power_entity or switch_entity
                if hist_entity:
                    accumulated, is_cycle_completed = await self.calculate_load_accumulated_hours(
                        hist_entity,
                        ha_timezone=resolved_tz,
                        now_utc=start_time,
                    )
                    if accumulated > 0.0:
                        load_copy.accumulated_hours_today = max(load_copy.accumulated_hours_today, accumulated)

                    if load_copy.complete_on_cutoff and is_cycle_completed and not load_copy.is_running:
                        load_copy.is_cycle_completed_today = True
                        logger.info(
                            f"Load '{load.name or load.id}' completed heating cycle today ({load_copy.accumulated_hours_today:.2f}h runtime, "
                            f"thermostat cutoff detected). Daily requirement marked satisfied."
                        )
                    else:
                        logger.info(
                            f"Load '{load.name or load.id}' accumulated runtime today: {load_copy.accumulated_hours_today:.2f}h / "
                            f"{load_copy.required_hours or 0.0:.2f}h required (remaining: {load_copy.remaining_hours_needed:.2f}h)."
                        )

                updated_loads.append(load_copy)

        # --- 7. Real-time load blending: blend instantaneous baseline into leading steps ---
        if actual_house_power is not None and len(load_forecast) > 0:
            active_deferrable_power = sum(
                l.active_power_w
                for l in updated_loads
                if getattr(l, "is_included_in_total_load", True)
            )
            effective_baseline_now = max(0.0, actual_house_power - active_deferrable_power)
            load_forecast[0] = effective_baseline_now
            if len(load_forecast) > 1:
                load_forecast[1] = round(0.5 * effective_baseline_now + 0.5 * load_forecast[1], 1)
            if len(load_forecast) > 2:
                load_forecast[2] = round(0.25 * effective_baseline_now + 0.75 * load_forecast[2], 1)
            logger.info(
                f"Blended live baseline power ({effective_baseline_now:.1f} W = {actual_house_power:.1f}W house - "
                f"{active_deferrable_power:.1f}W deferrable) into immediate forecast steps: "
                f"[{load_forecast[0]:.0f}W, {load_forecast[1]:.0f}W, {load_forecast[2] if len(load_forecast) > 2 else 0:.0f}W]"
            )

        logger.info(
            f"Assembled Home Assistant payload successfully: {len(timestamps)} timestamps, "
            f"{len(solar_forecast)} solar steps, {len(buy_prices)} price steps, {len(load_forecast)} load steps, "
            f"{len(updated_loads)} deferrable loads."
        )

        return HomeAssistantPayload(
            timestamps=timestamps,
            solar_forecast=solar_forecast,
            buy_prices=buy_prices,
            sell_prices=sell_prices,
            load_forecast=load_forecast,
            actual_load_power_w=actual_house_power,
            actual_solar_power_w=actual_solar_power,
            actual_buy_price=actual_buy_price,
            actual_sell_price=actual_sell_price,
            battery_soc=battery_soc,
            deferrable_loads=updated_loads,
            prediction_horizon_days=horizon_days,
            load_history_days=load_history_days,
            ha_timezone=resolved_tz,
            force_reoptimize=force_reoptimize,
        )

    def _parse_float_state(self, state_obj: Optional[Dict[str, Any]]) -> Optional[float]:
        """Safely parses state numeric string to float."""
        if not state_obj or "state" not in state_obj:
            return None
        st = state_obj["state"]
        if st in ("unknown", "unavailable", "None", ""):
            return None
        try:
            return float(st)
        except (ValueError, TypeError):
            return None

