"""
FluxEM: Custom Home Energy Optimization Microservice for Home Assistant.
FastAPI Web Service, WebUI Dashboard, Home Assistant Direct Sync, Baseline Telemetry, and Webhook Endpoints.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from fluxem import __version__
from fluxem.config import settings
from fluxem.ingestion.pipeline import IngestionPipeline
from fluxem.integrations.homeassistant import HomeAssistantClient
from fluxem.models.payload import HomeAssistantPayload
from fluxem.models.response import (
    HealthResponse,
    IngestionSummaryResponse,
    OptimizationScheduleResponse,
)
from fluxem.models.telemetry import (
    DashboardDataResponse,
    PlanAdherenceMetrics,
    TimestepActual,
)
from fluxem.mqtt.publisher import MQTTPublisher
from fluxem.optimization.engine import OptimizationEngine
from fluxem.storage import config_store, telemetry_store
from fluxem.ui import render_ui_html
from fluxem.watchdog.watchdog import DriftWatchdog

# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fluxem")

_start_time = time.time()

# Initialize core microservice modules
ingestion_pipeline = IngestionPipeline()
optimization_engine = OptimizationEngine()
drift_watchdog = DriftWatchdog()
mqtt_publisher = MQTTPublisher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for FastAPI application."""
    global _start_time
    _start_time = time.time()
    logger.info(
        f"Starting {settings.app_name} v{__version__} on {settings.host}:{settings.port} "
        f"[env: {settings.environment}]"
    )

    # Connect to MQTT Broker if enabled
    if config_store.config.mqtt_enabled or settings.mqtt_enabled:
        mqtt_publisher.reconfigure(
            host=config_store.config.mqtt_broker_host or settings.mqtt_broker_host,
            port=config_store.config.mqtt_broker_port or settings.mqtt_broker_port,
            username=config_store.config.mqtt_username or settings.mqtt_username,
            password=config_store.config.mqtt_password or settings.mqtt_password,
            topic_prefix=config_store.config.mqtt_topic_prefix or settings.mqtt_topic_prefix,
            enabled=True,
        )

    yield

    # Disconnect from MQTT Broker
    if mqtt_publisher.enabled:
        mqtt_publisher.disconnect()

    logger.info(f"Shutting down {settings.app_name}...")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "FluxEM: A lightweight, self-hosted energy optimization microservice for Home Assistant. "
        "Provides transparent, predictable home energy scheduling, battery arbitrage, and deferrable load management."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for local Home Assistant and web UI interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["WebUI & System"])
async def root(request: Request) -> Any:
    """Serves the interactive WebUI dashboard for browsers, or service status JSON for API clients."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return render_ui_html()
    return {
        "service": settings.app_name,
        "version": __version__,
        "status": "online",
        "documentation": "/docs",
        "web_ui": "/ui",
    }


@app.get("/ui", tags=["WebUI"], response_class=HTMLResponse)
async def get_ui():
    """WebUI interactive configuration dashboard."""
    return render_ui_html()


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """Service health and uptime check."""
    uptime = time.time() - _start_time
    return HealthResponse(
        status="healthy",
        version=__version__,
        app_name=settings.app_name,
        environment=settings.environment,
        uptime_seconds=round(uptime, 2),
    )


@app.get("/api/v1/config", tags=["Configuration"])
async def get_config() -> Dict[str, Any]:
    """View active runtime settings."""
    cfg = config_store.config
    return {
        "app_name": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "default_timestep_minutes": cfg.default_timestep_minutes,
        "min_horizon_hours": cfg.min_horizon_hours,
        "prediction_horizon_days": cfg.prediction_horizon_days,
        "load_history_days": cfg.load_history_days,
        "load_forecast_method": cfg.load_forecast_method,
        "max_horizon_hours": cfg.max_horizon_hours,
        "enable_export_arbitrage": cfg.enable_export_arbitrage,
        "min_arbitrage_profit_per_kwh": cfg.min_arbitrage_profit_per_kwh,
        "battery_degradation_cost_per_kwh": cfg.battery_degradation_cost_per_kwh,
        "mqtt_enabled": cfg.mqtt_enabled,
        "mqtt_topic_prefix": cfg.mqtt_topic_prefix,
        "ha_url": cfg.ha_url,
        "ha_configured": bool(cfg.ha_url and cfg.ha_token),
        "drift_thresholds": {
            "solar_pct": cfg.solar_drift_threshold_pct,
            "price_pct": cfg.price_drift_threshold_pct,
            "load_pct": cfg.load_drift_threshold_pct,
            "soc_pct": cfg.soc_drift_threshold_pct,
        },
    }


@app.get("/api/v1/ui/config", tags=["WebUI"])
async def get_ui_config() -> Dict[str, Any]:
    """Retrieve current persistent WebUI configuration."""
    return config_store.config.model_dump()


@app.post("/api/v1/ui/config", tags=["WebUI"])
async def save_ui_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Save updated WebUI configuration to persistent disk storage."""
    try:
        updated = config_store.update_from_dict(data)
        # Update watchdog thresholds dynamically
        drift_watchdog.solar_threshold_pct = updated.solar_drift_threshold_pct
        drift_watchdog.price_threshold_pct = updated.price_drift_threshold_pct
        drift_watchdog.load_threshold_pct = updated.load_drift_threshold_pct
        drift_watchdog.soc_threshold_pct = updated.soc_drift_threshold_pct

        # Update MQTT publisher dynamically
        mqtt_publisher.reconfigure(
            host=updated.mqtt_broker_host or "localhost",
            port=updated.mqtt_broker_port or 1883,
            username=updated.mqtt_username,
            password=updated.mqtt_password,
            topic_prefix=updated.mqtt_topic_prefix or "fluxem",
            enabled=updated.mqtt_enabled,
        )

        return {
            "status": "success",
            "message": "Configuration saved successfully",
            "config": updated.model_dump(),
        }
    except Exception as e:
        logger.error(f"Error saving WebUI configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Configuration error: {str(e)}",
        )


@app.get("/api/v1/ui/dashboard", response_model=DashboardDataResponse, tags=["WebUI"])
async def get_dashboard_data() -> DashboardDataResponse:
    """
    Returns aggregated dashboard dataset: local date & time, today's Baseline Plan of Record,
    active optimized schedule, interval actuals, and plan adherence metrics.
    """
    cfg = config_store.config
    watchdog_status = "nominal"
    watchdog_reason = ""
    if drift_watchdog.cached_plan:
        watchdog_status = "holding_plan"
        watchdog_reason = "Holding active baseline plan"

    return telemetry_store.get_dashboard_data(
        ha_timezone=cfg.ha_timezone,
        horizon_days=cfg.prediction_horizon_days,
        watchdog_status=watchdog_status,
        watchdog_reason=watchdog_reason,
    )


@app.post("/api/v1/baseline/lock", tags=["Telemetry & Baseline"])
async def lock_baseline_plan() -> Dict[str, Any]:
    """Manually locks today's current optimization schedule as the Baseline Plan of Record."""
    telemetry_store.lock_baseline_plan()
    return {
        "status": "success",
        "message": "Today's Baseline Plan of Record has been locked successfully.",
        "is_locked": True,
    }


@app.post("/api/v1/baseline/reset", tags=["Telemetry & Baseline"])
async def reset_baseline_plan() -> Dict[str, Any]:
    """Resets today's baseline plan to allow a fresh schedule to be established."""
    telemetry_store.reset_baseline_plan()
    drift_watchdog.clear_cache()
    return {
        "status": "success",
        "message": "Today's Baseline Plan of Record has been reset.",
        "is_locked": False,
    }


# --- Home Assistant Direct Integration Endpoints ---

@app.post("/api/v1/ha/test-connection", tags=["Home Assistant Integration"])
async def test_ha_connection(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Test connection to Home Assistant using stored or provided credentials."""
    cfg = config_store.config
    url = data.get("ha_url") if data else cfg.ha_url
    token = data.get("ha_token") if data else cfg.ha_token

    client = HomeAssistantClient(base_url=url, access_token=token)
    success, message, info = await client.test_connection()
    if not success:
        return {"status": "error", "message": message, "connected": False}

    return {
        "status": "success",
        "message": message,
        "connected": True,
        "ha_version": info.get("version", "unknown"),
        "location_name": info.get("location_name", "Home Assistant"),
        "time_zone": info.get("time_zone", "UTC"),
    }


@app.api_route("/api/v1/ha/entities", methods=["GET", "POST"], tags=["Home Assistant Integration"])
async def get_ha_entities(
    ha_url: Optional[str] = None,
    ha_token: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Fetch all available entities from Home Assistant for UI dropdown selection."""
    cfg = config_store.config
    url = ha_url or (data.get("ha_url") if data else None) or cfg.ha_url
    token = ha_token or (data.get("ha_token") if data else None) or cfg.ha_token

    client = HomeAssistantClient(base_url=url, access_token=token)
    return await client.fetch_entities()


@app.post("/api/v1/ha/sync-and-optimize", response_model=OptimizationScheduleResponse, tags=["Home Assistant Integration"])
async def sync_ha_and_optimize() -> OptimizationScheduleResponse:
    """
    Directly pulls live sensor states and forecast attributes from Home Assistant,
    assembles the payload, and executes optimization without needing a Home Assistant automation.
    """
    cfg = config_store.config
    client = HomeAssistantClient(base_url=cfg.ha_url, access_token=cfg.ha_token)

    if not client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Home Assistant API is not configured. Please enter your HA URL and Long-Lived Access Token in WebUI.",
        )

    try:
        payload = await client.build_payload_from_entities(
            mappings=cfg.ha_entity_mappings,
            configured_loads=cfg.deferrable_loads,
            prediction_horizon_days=cfg.prediction_horizon_days,
            load_history_days=cfg.load_history_days,
            load_forecast_method=cfg.load_forecast_method,
            ha_timezone=cfg.ha_timezone,
            force_reoptimize=True,
        )
        return await optimize(payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error syncing with Home Assistant")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Home Assistant sync error: {str(e)}",
        )


# --- MQTT Endpoints ---

@app.post("/api/v1/mqtt/test-connection", tags=["MQTT"])
async def test_mqtt_connection(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Test connection to MQTT broker using stored or provided credentials."""
    cfg = config_store.config
    host = (data.get("mqtt_broker_host") if data else None) or cfg.mqtt_broker_host or "localhost"
    port = int((data.get("mqtt_broker_port") if data else None) or cfg.mqtt_broker_port or 1883)
    username = data.get("mqtt_username") if data else cfg.mqtt_username
    password = data.get("mqtt_password") if data else cfg.mqtt_password

    success, message = MQTTPublisher.test_broker_connection(
        host=host,
        port=port,
        username=username,
        password=password,
    )
    if not success:
        return {"status": "error", "message": message, "connected": False}

    return {"status": "success", "message": message, "connected": True}


# --- Simulation & Ingestion Endpoints ---

@app.post("/api/v1/ui/simulate", response_model=OptimizationScheduleResponse, tags=["WebUI"])
async def simulate_ui_optimization() -> OptimizationScheduleResponse:
    """
    Runs a realistic 48-timestep (midnight-to-midnight) simulation with realistic solar curve,
    time-of-use pricing tariffs, household loads, and simulated past actuals showing realistic drift.
    """
    cfg = config_store.config
    tz_str = cfg.ha_timezone if cfg.ha_timezone not in ("auto", "none", "") else "UTC"
    try:
        tz_obj = ZoneInfo(tz_str)
    except Exception:
        tz_obj = timezone.utc

    now_local = datetime.now(tz_obj)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_local.astimezone(timezone.utc)

    # 48 intervals (24 hours at 30-minute intervals)
    target_steps = 48
    target_dt_list = [midnight_utc + timedelta(minutes=30 * i) for i in range(target_steps)]
    timestamps = [dt.strftime("%Y-%m-%dT%H:%M:%SZ") for dt in target_dt_list]

    # Realistic 48-step Pricing Curves ($/kWh)
    buy_prices = [
        0.18, 0.18, 0.17, 0.17, 0.17, 0.18, 0.19, 0.22,  # 00:00 - 03:30 (Overnight Off-Peak)
        0.28, 0.36, 0.44, 0.40, 0.32, 0.24, 0.16, 0.12,  # 04:00 - 07:30 (Morning Peak ramp)
        0.08, 0.06, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15,  # 08:00 - 11:30 (Solar Valley dip)
        0.18, 0.22, 0.26, 0.32, 0.38, 0.46, 0.54, 0.58,  # 12:00 - 15:30 (Afternoon -> Evening peak)
        0.52, 0.48, 0.42, 0.35, 0.28, 0.24, 0.22, 0.20,  # 16:00 - 19:30 (Evening peak wind-down)
        0.19, 0.18, 0.18, 0.18, 0.18, 0.18, 0.17, 0.17,  # 20:00 - 23:30 (Night)
    ]

    sell_prices = [
        0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.06,
        0.08, 0.10, 0.12, 0.10, 0.08, 0.06, 0.04, 0.03,
        0.02, 0.01, 0.01, 0.02, 0.03, 0.04, 0.06, 0.08,
        0.10, 0.12, 0.14, 0.18, 0.22, 0.25, 0.28, 0.26,
        0.20, 0.16, 0.12, 0.09, 0.07, 0.06, 0.05, 0.05,
        0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
    ]

    # Realistic 48-step Solar Curve (0 at night, peaks ~6400W at 13:00)
    solar_forecast = [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,  # 00:00 - 05:30
        50.0, 250.0, 800.0, 1600.0, 2600.0, 3800.0, 4800.0, 5600.0, # 06:00 - 09:30
        6200.0, 6500.0, 6600.0, 6400.0, 5900.0, 5100.0, 4100.0, 3000.0, # 10:00 - 13:30
        1900.0, 950.0, 350.0, 80.0, 0.0, 0.0, 0.0, 0.0,             # 14:00 - 17:30
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,  # 18:00 - 23:30
    ]

    # Realistic 48-step Household Baseline Load Curve (Watts)
    load_forecast = [
        420.0, 400.0, 390.0, 380.0, 390.0, 410.0, 450.0, 550.0,
        850.0, 1400.0, 1650.0, 1300.0, 950.0, 750.0, 620.0, 580.0,
        540.0, 510.0, 500.0, 520.0, 550.0, 580.0, 620.0, 700.0,
        780.0, 850.0, 920.0, 1100.0, 1350.0, 1700.0, 2100.0, 2400.0,
        2250.0, 1950.0, 1600.0, 1200.0, 950.0, 750.0, 620.0, 550.0,
        500.0, 480.0, 450.0, 440.0, 430.0, 420.0, 410.0, 400.0,
    ]

    sample_payload = {
        "timestamps": timestamps,
        "buy_prices": buy_prices,
        "sell_prices": sell_prices,
        "solar_forecast": solar_forecast,
        "load_forecast": load_forecast,
        "target_timestep_minutes": 30,
        "force_reoptimize": True,
    }

    context = ingestion_pipeline.ingest(sample_payload)
    response = optimization_engine.optimize(context)

    # Establish as today's Baseline Plan of Record
    telemetry_store.set_baseline_plan(response, lock=False, tz_name=tz_str)
    telemetry_store.set_active_schedule(response, tz_name=tz_str)

    # Generate sample actuals for past elapsed intervals up to current local hour
    current_step_idx = min(47, max(0, (now_local.hour * 60 + now_local.minute) // 30))
    for idx in range(current_step_idx + 1):
        ts = timestamps[idx]
        planned_solar = solar_forecast[idx]
        planned_load = load_forecast[idx]
        # Simulate slight realistic cloud dips and load variations
        cloud_factor = 0.82 if 18 <= idx <= 26 else (0.95 if planned_solar > 0 else 1.0)
        sim_actual_solar = round(planned_solar * cloud_factor, 1)
        sim_actual_load = round(planned_load * 1.04, 1)
        sim_soc = None
        if response.battery_soc_percent and idx < len(response.battery_soc_percent):
            # Simulated SOC slightly trailing planned due to cloud cover
            sim_soc = round(max(10.0, response.battery_soc_percent[idx] - (1.5 if idx > 18 else 0.0)), 1)

        telemetry_store.record_actual(
            timestamp=ts,
            solar_power_w=sim_actual_solar,
            house_power_w=sim_actual_load,
            baseline_load_w=sim_actual_load,
            battery_soc_percent=sim_soc,
            battery_power_w=response.battery_power_w[idx] if response.battery_power_w else None,
            buy_price=buy_prices[idx],
            sell_price=sell_prices[idx],
            tz_name=tz_str,
        )

    return response


@app.post(
    "/api/v1/ingest",
    response_model=IngestionSummaryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Ingestion"],
)
async def ingest_data(payload: HomeAssistantPayload) -> IngestionSummaryResponse:
    """
    Validate and ingest Home Assistant sensor time-series data without triggering optimization.
    Useful for testing data feeds, sensor templates, and verifying unit normalization.
    """
    try:
        context = ingestion_pipeline.ingest(payload)
        return context.to_summary_response()
    except ValueError as e:
        logger.warning(f"Ingestion validation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Data ingestion error: {str(e)}",
        )
    except Exception as e:
        logger.exception("Unexpected error during data ingestion")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal ingestion error: {str(e)}",
        )


def _find_current_timestamp(timestamps: Optional[list[str]]) -> str:
    """Finds the timestamp corresponding to the current UTC timestep."""
    if not timestamps:
        return datetime.now(timezone.utc).isoformat()
    now_utc = datetime.now(timezone.utc)
    try:
        t_first = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
        t_last = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
        if now_utc < t_first:
            return timestamps[0]
        if now_utc > t_last + timedelta(minutes=30):
            return timestamps[0]
    except Exception:
        pass

    cur_ts = timestamps[0]
    for ts in timestamps:
        try:
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts_dt <= now_utc:
                cur_ts = ts
            else:
                break
        except Exception:
            continue
    return cur_ts


@app.post(
    "/api/v1/optimize",
    response_model=OptimizationScheduleResponse,
    status_code=status.HTTP_200_OK,
    tags=["Optimization"],
)
async def optimize(payload: HomeAssistantPayload) -> OptimizationScheduleResponse:
    """
    Main optimization entrypoint. Ingests data, evaluates drift watchdog,
    and produces optimized schedules for deferrable loads and battery storage.
    Updates baseline telemetry buffer and plan adherence metrics.
    """
    cfg = config_store.config
    tz_name = cfg.ha_timezone

    try:
        context = ingestion_pipeline.ingest(payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Data ingestion error: {str(e)}",
        )
    except Exception as e:
        logger.exception("Unexpected ingestion error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal ingestion error: {str(e)}",
        )

    # Evaluate Drift Watchdog (Module D)
    watchdog_decision = drift_watchdog.evaluate(
        context=context,
        force_reoptimize=payload.force_reoptimize,
    )

    if not watchdog_decision.should_reoptimize and drift_watchdog.cached_plan is not None:
        logger.info(f"Watchdog holding existing baseline plan: {watchdog_decision.reason}")
        cached = drift_watchdog.cached_plan
        response = OptimizationScheduleResponse(
            status="held_by_watchdog",
            execution_time_ms=0.0,
            timestamps=cached.timestamps,
            solar_forecast_w=cached.solar_forecast_w,
            baseline_load_w=cached.baseline_load_w,
            buy_prices=cached.buy_prices,
            sell_prices=cached.sell_prices,
            deferrable_load_power_w=cached.deferrable_load_power_w,
            battery_power_w=cached.battery_power_w,
            battery_soc_percent=cached.battery_soc_percent,
            grid_import_power_w=cached.grid_import_power_w,
            grid_export_power_w=cached.grid_export_power_w,
            summary=context.to_summary_response(),
            metadata={
                **cached.metadata,
                "watchdog": watchdog_decision.model_dump(),
            },
        )

        # Record current interval actuals into telemetry store
        cur_ts = _find_current_timestamp(response.timestamps)
        telemetry_store.record_actual(
            timestamp=cur_ts,
            solar_power_w=context.actual_sensors.get("solar_power_w"),
            house_power_w=context.actual_sensors.get("total_house_power_w"),
            baseline_load_w=context.actual_baseline_load_w,
            battery_soc_percent=context.battery.soc_percent if context.battery else None,
            buy_price=context.actual_sensors.get("buy_price"),
            sell_price=context.actual_sensors.get("sell_price"),
            tz_name=tz_name,
        )

        if settings.mqtt_enabled or cfg.mqtt_enabled:
            mqtt_publisher.publish_optimization_result(response)
        return response

    # Execute full optimization
    response = optimization_engine.optimize(
        context=context,
        enable_export_arbitrage=payload.enable_export_arbitrage,
        min_arbitrage_profit_per_kwh=payload.min_arbitrage_profit_per_kwh,
        battery_degradation_cost_per_kwh=payload.battery_degradation_cost_per_kwh,
        max_grid_export_power_w=payload.max_grid_export_power_w,
    )

    # Attach watchdog decision metadata and update cache
    response.metadata["watchdog"] = watchdog_decision.model_dump()
    drift_watchdog.update_cached_plan(response)

    # Update active schedule and record current telemetry
    telemetry_store.set_active_schedule(response, tz_name=tz_name)
    cur_ts = _find_current_timestamp(response.timestamps)
    telemetry_store.record_actual(
        timestamp=cur_ts,
        solar_power_w=context.actual_sensors.get("solar_power_w"),
        house_power_w=context.actual_sensors.get("total_house_power_w"),
        baseline_load_w=context.actual_baseline_load_w,
        battery_soc_percent=context.battery.soc_percent if context.battery else None,
        buy_price=context.actual_sensors.get("buy_price"),
        sell_price=context.actual_sensors.get("sell_price"),
        tz_name=tz_name,
    )

    # Publish updated schedule to MQTT
    if settings.mqtt_enabled or cfg.mqtt_enabled:
        mqtt_publisher.publish_optimization_result(response)

    return response


@app.post("/api/v1/webhook", tags=["Integration"])
async def webhook(payload: HomeAssistantPayload) -> OptimizationScheduleResponse:
    """
    Direct Webhook endpoint for Home Assistant Automations (e.g. state triggers or cron).
    """
    return await optimize(payload)
