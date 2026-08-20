# FluxEM ⚡

**FluxEM** is a lightweight, self-hosted energy optimization microservice engineered for [Home Assistant](https://www.home-assistant.io/). It serves as a modern, transparent, and predictable alternative to EMHASS by eliminating rigid solver constraints, supporting agnostic data inputs, and providing intelligent event-driven re-optimization.

---

## 🏗️ Architecture & Core Modules

FluxEM is built with Python 3.12, FastAPI, Pandas, and NumPy:

- **Module A: Agnostic Data Ingestion (Bring Your Own Sensors)**:
  - Ingests flat time-series arrays or structured records from any Home Assistant integration (Solcast, Amber, Tibber, Nordpool, etc.).
  - Automatic frequency detection and alignment to uniform intervals (5, 15, 30, 60 minutes).
  - Robust data validation, NaN / missing value imputation, non-monotonic sorting, and unit conversion (W vs kW, $/kWh vs c/kWh).
  - **Zero-Helper Deferrable Load Deduction**: Automatically computes pure baseline home demand ($\text{Baseline} = \text{house\_power} - \sum \text{deferrable\_power}$) so you don't need custom Home Assistant template sensors.
- **Module B: Flexible Deferrable Load Management**:
  - **Continuous Mode (`continuous: true`)**: Enforces strict unbroken runs for thermal loads (hot water, heat pumps) and preserves active mid-cycle states from step 0.
  - **Flexible Mode (`continuous: false`)**: Optimizes split runs across cheap price dips and solar peaks while enforcing equipment cycle constraints (`max_starts_per_day`).
  - Priority-based solar stacking and time window boundaries (`window_start_time` / `window_end_time`).
- **Module C: Intelligent Grid Pre-Charging & Dynamic Battery Arbitrage**:
  - **Deficit Pre-Charging**: Looks ahead for future expensive peak import periods when the battery would be exhausted, scheduling just-in-time off-peak grid charging.
  - **Dynamic Export Arbitrage (Optional Mode)**: Evaluates feed-in price spikes against cheap import rates and round-trip efficiency losses ($\eta_{\text{round\_trip}} \times P_{\text{sell}} - P_{\text{buy}} - \text{wear} \ge \text{margin}$), charging from the grid to export at peak feed-in tariffs.
- **Module D: Drift-Triggered MPC (Smart Watchdog)**:
  - Variance watchdog comparing real-time sensor measurements against forecasted curves.
  - Holds existing baseline plans when within tolerances, re-optimizing only on statistical drift (solar cloud cover, spot price spikes, load surges).
- **Module E: Direct Home Assistant API & MQTT Integration**:
  - **Direct HA API (Zero-YAML)**: Connects directly to Home Assistant using a Long-Lived Access Token to auto-discover entities and fetch solar & price forecasts.
  - **Historical Load Forecasting**: Analyzes past consumption history over a configurable lookahead (1 to 14 days) to generate household load curves.
  - **Configurable Lookahead Horizon**: Plan optimizations across **1 Day (24h)**, **2 Days (48h)**, or **3 Days (72h)**.
  - **MQTT & Real-Time Controls**: Streams scheduled power curves, real-time switch commands (`ON`/`OFF`), and HA discovery payloads.

---

## 🎨 Interactive WebUI Dashboard

Access the browser interface at **`http://<FLUXEM_IP>:8000/ui`**:
- 🎛️ **Deferrable Loads Manager**: Add, edit, and delete appliances with continuous/flexible toggles.
- 🔋 **Battery Storage Configuration**: Usable capacity, SOC limits, and efficiency rates.
- 🏠 **Home Assistant API & Horizon**: Select **1, 2, or 3 Days** lookahead and **1 to 14 Days** history for home load forecasting.
- 📈 **Dynamic Arbitrage**: Configure grid pre-charging and feed-in export trading.
- 🐕 **Drift Watchdog**: Visual sliders for solar, price, and load variance thresholds.
- 📊 **Live Preview & Simulation**: Interactive Chart.js power curve graph.

---

## 🚀 Quickstart

### Running locally with Virtualenv
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the FastAPI service
uvicorn fluxem.main:app --host 0.0.0.0 --port 8000 --reload
```

### Running with Docker
```bash
docker build -t fluxem:latest .
docker run -d --name fluxem --restart unless-stopped -p 8000:8000 -v $(pwd)/data:/app/data fluxem:latest
```

---

## 📡 API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/ui` | Interactive WebUI dashboard & configuration page |
| `GET` | `/health` | Service health and uptime check |
| `GET` | `/api/v1/config` | View active configuration and thresholds |
| `POST` | `/api/v1/ha/test-connection` | Verify Home Assistant URL and Long-Lived Token |
| `POST` | `/api/v1/ha/sync-and-optimize` | Pull live sensors from HA & execute optimization |
| `POST` | `/api/v1/optimize` | Execute optimization, watchdog evaluation, and schedule generation |
| `POST` | `/api/v1/webhook` | Direct webhook trigger for Home Assistant automations |
| `GET` | `/docs` | Interactive OpenAPI Swagger UI documentation |

---

## 🧪 Testing

```bash
# Run full pytest test suite with coverage
.venv/bin/pytest -v --cov=fluxem --cov-report=term-missing
```
