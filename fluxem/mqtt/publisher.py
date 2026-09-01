"""
MQTT Communication Layer & Home Assistant Virtual Sensors Publisher (Module E).
Publishes optimized power schedules, real-time switch states, and Home Assistant MQTT Discovery payloads.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple
import paho.mqtt.client as mqtt

from fluxem import __version__
from fluxem.config import settings
from fluxem.models.response import OptimizationScheduleResponse

logger = logging.getLogger("fluxem.mqtt")


class MQTTPublisher:
    """
    Handles connection and publishing of scheduled power curves to an MQTT broker
    for seamless integration with Home Assistant sensors and automations.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        topic_prefix: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        self.host = host or settings.mqtt_broker_host
        self.port = port or settings.mqtt_broker_port
        self.username = username or settings.mqtt_username
        self.password = password or settings.mqtt_password
        self.topic_prefix = topic_prefix or settings.mqtt_topic_prefix
        self.enabled = enabled if enabled is not None else settings.mqtt_enabled

        self.client: Optional[mqtt.Client] = None
        self._is_connected = False

    def connect(self) -> bool:
        """Establishes connection to the MQTT broker."""
        if not self.enabled:
            logger.info("MQTT publishing is disabled in configuration.")
            return False

        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"fluxem_{settings.environment}",
            )

            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)

            # Setup Last Will and Testament (LWT)
            lwt_topic = f"{self.topic_prefix}/status"
            self.client.will_set(lwt_topic, payload="offline", qos=1, retain=True)

            self.client.connect(self.host, self.port, keepalive=settings.mqtt_keepalive)
            self.client.loop_start()

            # Publish online status
            self.client.publish(lwt_topic, payload="online", qos=1, retain=True)
            self._is_connected = True
            logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to MQTT broker ({self.host}:{self.port}): {str(e)}")
            self._is_connected = False
            return False

    def disconnect(self):
        """Disconnects from the MQTT broker gracefully."""
        if self.client and self._is_connected:
            try:
                lwt_topic = f"{self.topic_prefix}/status"
                self.client.publish(lwt_topic, payload="offline", qos=1, retain=True)
                self.client.loop_stop()
                self.client.disconnect()
                self._is_connected = False
                logger.info("Disconnected from MQTT broker.")
            except Exception as e:
                logger.warning(f"Error disconnecting from MQTT broker: {str(e)}")

    @classmethod
    def test_broker_connection(
        cls,
        host: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 4.0,
    ) -> Tuple[bool, str]:
        """
        Attempts a quick connection to the specified MQTT broker and returns (success, message).
        """
        if not host:
            return False, "Broker host is required."

        import time as _time
        connected = False
        conn_error = ""

        def on_connect(client, userdata, flags, rc, properties=None):
            nonlocal connected, conn_error
            if hasattr(rc, "is_failure"):
                if not rc.is_failure:
                    connected = True
                else:
                    conn_error = str(rc)
            elif rc == 0:
                connected = True
            else:
                conn_error = f"Connection refused (code {rc})"

        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="fluxem_test_probe",
            )
            client.on_connect = on_connect

            if username and password:
                client.username_pw_set(username, password)

            client.connect(host, port, keepalive=10)
            client.loop_start()

            start_t = _time.time()
            while _time.time() - start_t < timeout:
                if connected or conn_error:
                    break
                _time.sleep(0.1)

            client.loop_stop()
            client.disconnect()

            if connected:
                return True, f"Successfully connected to MQTT broker at {host}:{port}"
            elif conn_error:
                return False, f"MQTT broker rejected connection: {conn_error}"
            else:
                return False, f"Connection to {host}:{port} timed out after {timeout:.0f}s"
        except Exception as e:
            return False, f"MQTT connection error: {str(e)}"

    def reconfigure(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        topic_prefix: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        """Updates broker configuration and reconnects if enabled."""
        self.disconnect()

        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password
        if topic_prefix is not None:
            self.topic_prefix = topic_prefix
        if enabled is not None:
            self.enabled = enabled

        if self.enabled:
            self.connect()

    @staticmethod
    def _find_current_step_index(timestamps: list[str]) -> int:
        """Finds the index of the interval containing the current UTC time."""
        if not timestamps:
            return 0
        from datetime import datetime, timezone, timedelta
        now_utc = datetime.now(timezone.utc)
        try:
            t_first = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            t_last = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            if now_utc < t_first:
                return 0
            if now_utc > t_last + timedelta(minutes=30):
                return 0
        except Exception:
            pass

        cur_idx = 0
        for idx, ts in enumerate(timestamps):
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if ts_dt <= now_utc:
                    cur_idx = idx
                else:
                    break
            except Exception:
                continue
        return cur_idx

    def publish_optimization_result(self, result: OptimizationScheduleResponse) -> bool:
        """
        Publishes optimized curves, real-time controls for the current timestep (NOW),
        full forecast attributes, and Home Assistant MQTT Discovery payloads.
        """
        if not self.enabled or not self.client or not self._is_connected:
            return False

        try:
            p = self.topic_prefix
            cur_idx = self._find_current_step_index(result.timestamps)

            # 1. Summary & Watchdog Status
            self._publish(f"{p}/status", "online", retain=True)
            self._publish(f"{p}/summary", json.dumps(result.summary.model_dump()), retain=True)
            self._publish(f"{p}/timestamps", json.dumps(result.timestamps), retain=True)

            # 2. Deferrable Loads Curves & Immediate Switch States
            for load_id, power_curve in result.deferrable_load_power_w.items():
                current_power = power_curve[cur_idx] if power_curve and cur_idx < len(power_curve) else 0.0
                switch_state = "ON" if current_power > 10.0 else "OFF"

                # Publish schedule array and JSON attributes for HA graphs / apexcharts
                self._publish(f"{p}/deferrable_loads/{load_id}/power_curve", json.dumps(power_curve), retain=True)
                self._publish(f"{p}/deferrable_loads/{load_id}/schedule_json", json.dumps({
                    "timestamps": result.timestamps,
                    "power_curve_w": power_curve,
                    "current_setpoint_w": round(current_power, 1),
                    "switch_state": switch_state,
                }), retain=True)

                # Publish immediate state and power setpoint for HA automations
                self._publish(f"{p}/deferrable_loads/{load_id}/state", switch_state, retain=True)
                self._publish(f"{p}/deferrable_loads/{load_id}/current_setpoint_w", str(round(current_power, 1)), retain=True)

            # 3. Battery Schedules & Setpoints
            if result.battery_power_w:
                current_batt_w = result.battery_power_w[cur_idx] if cur_idx < len(result.battery_power_w) else 0.0
                self._publish(f"{p}/battery/power_curve", json.dumps(result.battery_power_w), retain=True)
                self._publish(f"{p}/battery/current_power_setpoint_w", str(round(current_batt_w, 1)), retain=True)

            if result.battery_soc_percent:
                current_soc = result.battery_soc_percent[cur_idx] if cur_idx < len(result.battery_soc_percent) else 0.0
                self._publish(f"{p}/battery/soc_curve", json.dumps(result.battery_soc_percent), retain=True)
                self._publish(f"{p}/battery/projected_soc", str(round(current_soc, 1)), retain=True)

            # 4. Grid Import / Export / Precharge Power Curves
            if result.grid_import_power_w:
                current_import_w = result.grid_import_power_w[cur_idx] if cur_idx < len(result.grid_import_power_w) else 0.0
                self._publish(f"{p}/grid/import_power_curve", json.dumps(result.grid_import_power_w), retain=True)
                self._publish(f"{p}/grid/current_import_setpoint_w", str(round(current_import_w, 1)), retain=True)

            if result.grid_export_power_w:
                current_export_w = result.grid_export_power_w[cur_idx] if cur_idx < len(result.grid_export_power_w) else 0.0
                self._publish(f"{p}/grid/export_power_curve", json.dumps(result.grid_export_power_w), retain=True)
                self._publish(f"{p}/grid/current_export_setpoint_w", str(round(current_export_w, 1)), retain=True)

            # Dedicated Battery Grid Pre-Charge (ONLY active when FluxEM explicitly requests charging battery from grid)
            if result.grid_precharge_power_w:
                current_precharge_w = result.grid_precharge_power_w[cur_idx] if cur_idx < len(result.grid_precharge_power_w) else 0.0
                self._publish(f"{p}/battery/grid_precharge_curve", json.dumps(result.grid_precharge_power_w), retain=True)
                self._publish(f"{p}/battery/grid_precharge_setpoint_w", str(round(current_precharge_w, 1)), retain=True)

            # Dedicated Wholesale Arbitrage Export (ONLY active when FluxEM explicitly requests battery export to grid)
            if result.arbitrage_export_power_w:
                current_arb_export_w = result.arbitrage_export_power_w[cur_idx] if cur_idx < len(result.arbitrage_export_power_w) else 0.0
                self._publish(f"{p}/battery/arbitrage_export_curve", json.dumps(result.arbitrage_export_power_w), retain=True)
                self._publish(f"{p}/battery/arbitrage_export_setpoint_w", str(round(current_arb_export_w, 1)), retain=True)

            # 5. Full Schedule Forecast Attributes (for Lovelace ApexCharts)
            forecast_attrs = {
                "timestamps": result.timestamps,
                "solar_forecast_w": result.solar_forecast_w,
                "baseline_load_w": result.baseline_load_w,
                "buy_prices": result.buy_prices,
                "sell_prices": result.sell_prices,
                "battery_power_w": result.battery_power_w,
                "battery_soc_percent": result.battery_soc_percent,
                "grid_import_power_w": result.grid_import_power_w,
                "grid_export_power_w": result.grid_export_power_w,
                "grid_precharge_power_w": result.grid_precharge_power_w,
                "arbitrage_export_power_w": result.arbitrage_export_power_w,
                "deferrable_load_power_w": result.deferrable_load_power_w,
                "updated_at": result.summary.start_time,
            }
            self._publish(f"{p}/forecast_attributes", json.dumps(forecast_attrs), retain=True)

            # 6. Metadata and Watchdog Telemetry
            if "watchdog" in result.metadata:
                wd = result.metadata["watchdog"]
                self._publish(f"{p}/watchdog/decision", json.dumps(wd), retain=True)
                reason_str = wd.get("reason", "Optimized") if isinstance(wd, dict) else "Optimized"
                self._publish(f"{p}/watchdog/reason", str(reason_str)[:250], retain=True)

            # 7. Ensure Home Assistant Discovery is up to date
            self.publish_home_assistant_discovery(list(result.deferrable_load_power_w.keys()))

            logger.info("Successfully published optimization results and discovery to MQTT broker.")
            return True
        except Exception as e:
            logger.error(f"Failed to publish optimization results to MQTT: {str(e)}")
            return False

    def publish_home_assistant_discovery(self, deferrable_load_ids: list[str]) -> bool:
        """
        Publishes Home Assistant MQTT Discovery configuration payloads
        so all FluxEM virtual sensors and binary switches appear automatically under
        Home Assistant > Settings > Devices & Services > MQTT.
        """
        if not self.enabled or not self.client or not self._is_connected:
            return False

        try:
            p = self.topic_prefix
            device_info = {
                "identifiers": ["fluxem_energy_optimizer"],
                "name": "FluxEM Energy Optimizer",
                "manufacturer": "FluxEM",
                "model": f"v{__version__}",
                "sw_version": __version__,
            }

            # 1. Engine Status Sensor
            self._publish(
                f"homeassistant/sensor/{p}/status/config",
                json.dumps({
                    "name": "FluxEM Engine Status",
                    "state_topic": f"{p}/status",
                    "unique_id": f"{p}_engine_status",
                    "icon": "mdi:lightning-bolt",
                    "device": device_info,
                }),
                retain=True,
            )

            # 2. Battery Target Power Sensor
            self._publish(
                f"homeassistant/sensor/{p}/battery_target_power/config",
                json.dumps({
                    "name": "FluxEM Battery Target Power",
                    "state_topic": f"{p}/battery/current_power_setpoint_w",
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "unique_id": f"{p}_battery_target_power",
                    "icon": "mdi:battery-charging",
                    "device": device_info,
                }),
                retain=True,
            )

            # 3. Battery Projected SOC Sensor
            self._publish(
                f"homeassistant/sensor/{p}/battery_projected_soc/config",
                json.dumps({
                    "name": "FluxEM Battery Projected SOC",
                    "state_topic": f"{p}/battery/projected_soc",
                    "unit_of_measurement": "%",
                    "device_class": "battery",
                    "unique_id": f"{p}_battery_projected_soc",
                    "icon": "mdi:battery-high",
                    "device": device_info,
                }),
                retain=True,
            )

            # 4. Battery Dedicated Grid Pre-Charge Target Sensor (ONLY non-zero for forced grid charging)
            self._publish(
                f"homeassistant/sensor/{p}/battery_grid_precharge_target/config",
                json.dumps({
                    "name": "FluxEM Battery Grid Precharge Target",
                    "state_topic": f"{p}/battery/grid_precharge_setpoint_w",
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "unique_id": f"{p}_battery_grid_precharge_target",
                    "icon": "mdi:battery-arrow-up-outline",
                    "device": device_info,
                }),
                retain=True,
            )

            # 5. Battery Dedicated Wholesale Arbitrage Export Target Sensor
            self._publish(
                f"homeassistant/sensor/{p}/battery_arbitrage_export_target/config",
                json.dumps({
                    "name": "FluxEM Battery Arbitrage Export Target",
                    "state_topic": f"{p}/battery/arbitrage_export_setpoint_w",
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "unique_id": f"{p}_battery_arbitrage_export_target",
                    "icon": "mdi:battery-arrow-down-outline",
                    "device": device_info,
                }),
                retain=True,
            )

            # 6. Grid Import Target Sensor (Total Household Import)
            self._publish(
                f"homeassistant/sensor/{p}/grid_import_target/config",
                json.dumps({
                    "name": "FluxEM Grid Import Target",
                    "state_topic": f"{p}/grid/current_import_setpoint_w",
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "unique_id": f"{p}_grid_import_target",
                    "icon": "mdi:transmission-tower-import",
                    "device": device_info,
                }),
                retain=True,
            )

            # 7. Grid Export Target Sensor (Total Household Export)
            self._publish(
                f"homeassistant/sensor/{p}/grid_export_target/config",
                json.dumps({
                    "name": "FluxEM Grid Export Target",
                    "state_topic": f"{p}/grid/current_export_setpoint_w",
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "unique_id": f"{p}_grid_export_target",
                    "icon": "mdi:transmission-tower-export",
                    "device": device_info,
                }),
                retain=True,
            )

            # 6. Full Schedule Forecast Sensor (Attributes for ApexCharts)
            self._publish(
                f"homeassistant/sensor/{p}/schedule_forecast/config",
                json.dumps({
                    "name": "FluxEM Schedule Forecast",
                    "state_topic": f"{p}/status",
                    "json_attributes_topic": f"{p}/forecast_attributes",
                    "unique_id": f"{p}_schedule_forecast",
                    "icon": "mdi:chart-areaspline",
                    "device": device_info,
                }),
                retain=True,
            )

            # 7. Watchdog Drift Reason Sensor
            self._publish(
                f"homeassistant/sensor/{p}/watchdog_reason/config",
                json.dumps({
                    "name": "FluxEM Watchdog Reason",
                    "state_topic": f"{p}/watchdog/reason",
                    "json_attributes_topic": f"{p}/watchdog/decision",
                    "unique_id": f"{p}_watchdog_reason",
                    "icon": "mdi:shield-sync",
                    "device": device_info,
                }),
                retain=True,
            )

            # 8. Deferrable load switches and power sensors
            for load_id in deferrable_load_ids:
                clean_name = load_id.replace("_", " ").title()

                # Binary switch state sensor (ON/OFF)
                self._publish(
                    f"homeassistant/binary_sensor/{p}/{load_id}_state/config",
                    json.dumps({
                        "name": f"FluxEM {clean_name} Switch State",
                        "state_topic": f"{p}/deferrable_loads/{load_id}/state",
                        "payload_on": "ON",
                        "payload_off": "OFF",
                        "unique_id": f"{p}_{load_id}_switch_state",
                        "icon": "mdi:power",
                        "device": device_info,
                    }),
                    retain=True,
                )

                # Target Power setpoint sensor (W)
                self._publish(
                    f"homeassistant/sensor/{p}/{load_id}_target_power/config",
                    json.dumps({
                        "name": f"FluxEM {clean_name} Target Power",
                        "state_topic": f"{p}/deferrable_loads/{load_id}/current_setpoint_w",
                        "unit_of_measurement": "W",
                        "device_class": "power",
                        "unique_id": f"{p}_{load_id}_target_power",
                        "icon": "mdi:flash",
                        "device": device_info,
                    }),
                    retain=True,
                )

                # Full 24h schedule sensor (with attributes)
                self._publish(
                    f"homeassistant/sensor/{p}/{load_id}_schedule/config",
                    json.dumps({
                        "name": f"FluxEM {clean_name} Schedule",
                        "state_topic": f"{p}/deferrable_loads/{load_id}/state",
                        "json_attributes_topic": f"{p}/deferrable_loads/{load_id}/schedule_json",
                        "unique_id": f"{p}_{load_id}_schedule",
                        "icon": "mdi:chart-timeline-variant",
                        "device": device_info,
                    }),
                    retain=True,
                )

            return True
        except Exception as e:
            logger.error(f"Failed to publish Home Assistant discovery: {str(e)}")
            return False

    def _publish(self, topic: str, payload: str, qos: int = 1, retain: bool = True):
        """Internal helper to publish a single MQTT message."""
        if self.client:
            self.client.publish(topic, payload=payload, qos=qos, retain=retain)
