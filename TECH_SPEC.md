# Technical Specification: Custom Home Energy Optimization Engine ("Project FluxEM")

## 1. Overview & Objectives
A lightweight, self-hosted Python microservice designed to replace EMHASS for Home Assistant. It provides transparent, predictable home energy management by eliminating rigid solver constraints, supporting agnostic data inputs, and introducing intelligent, event-driven re-optimization.

## 2. Architecture & Tech Stack
- **Runtime Environment:** Standalone Docker container (Python 3.12+).
- **Core Framework:** FastAPI (for receiving webhook/REST payloads from Home Assistant).
- **Data Processing:** Pandas & NumPy (for time-series alignment and mathematical operations).
- **Communication Layer:** MQTT protocol for real-time publishing of optimized power curves back to Home Assistant.
- **Optimization Paradigm:** Deterministic/heuristic-hybrid scheduling engine combined with rule-based look-ahead logic (avoiding black-box linear programming failures).

## 3. Core Functional Modules

### A. Agnostic Data Ingestion (Bring Your Own Sensors) [Status: Implemented]
The engine accepts flat, unified time-series arrays or structured records from Home Assistant, decoupling it from specific third-party integrations (Solcast, Amber, Tibber, Nordpool, etc.).
- **Inputs:**
  - Timestamps (ISO-8601 array)
  - Buy Prices ($/kWh)
  - Sell Prices ($/kWh)
  - Solar Forecasts (Watts)
  - Baseline Home Load Forecasts (Watts)
  - Current Battery State of Charge (SOC %) & Capacity (kWh)
  - Deferrable Load States, Dedicated Consumption Sensors, & Accumulated Runtimes Today
  - Real-time whole-home consumption (`house_power` in Watts)
- **Automatic Deferrable Load Deduction (Zero-Helper Architecture):**
  - Eliminates the need for custom Home Assistant template helper sensors that manually subtract deferrable load powers from total house power.
  - Tracks individual deferrable load consumption sensors (`current_power_w`) or active running states (`nominal_power_w`).
  - Automatically calculates pure baseline demand:
    ```text
    Baseline Load (W) = max(0, house_power - sum(Active Deferrable Power))
    ```
  - Prevents double-counting loads when appliances are running mid-cycle.

### B. Flexible Deferrable Load Management
Per-load configuration profiles replacing global assumptions:
- **Critical / Mandatory Mode (`critical: true`):** Enforces mandatory daily completion for essential thermal/hygiene loads (hot water systems, heat pumps), scheduling within the optimal window even if grid import is required.
- **Opportunistic / Non-Critical Mode (`critical: false`):** Allows deferring non-essential loads (pool pumps, EV charging, dehumidifiers) when energy prices are high or solar is scarce.
  - **`max_skip_days`:** Configures maximum consecutive skip days before automatically promoting the load to a mandatory run.
  - **`max_buy_price`:** Configurable import price ceiling ($/kWh) below which grid running is allowed.
  - **`solar_only`:** Strict mode restricting operation exclusively to 100% surplus solar power.
- **Continuous Mode (`continuous: true`):** Enforces a strict, unbroken run for thermal loads once initiated. It respects active mid-cycle states and will not split runtime across days or take midday gaps.
- **Flexible Mode (`continuous: false`):** Allows splitting across optimal pricing/solar windows up to a maximum daily startup limit (`max_starts_per_day`).
- **State-Aware Tracking:** Automatically accounts for partial runtimes already accumulated today, preventing over-allocation or resetting running blocks.
- **Direct Consumption Metering (`current_power_w`):** Accepts real-time power draw from smart plugs/switches for exact load attribution.

### C. Intelligent Grid Pre-Charging & Dynamic Battery Arbitrage
A proactive look-ahead module that optimizes battery charging and energy trading:
1. **Deficit Pre-Charging (Self-Consumption Protection):**
   - Scans upcoming pricing and load forecasts for future expensive peaks (e.g., morning/evening spikes).
   - Calculates net energy deficit between forecasted load (including scheduled deferrable loads) and solar generation against available battery capacity.
   - If future import prices are significantly higher than current prices and the battery cannot cover the deficit, it calculates and schedules an optimal grid-charge window just in time.
2. **Dynamic Export Arbitrage (Wholesale / Feed-In Trading) [Optional Mode]:**
   - **Mode Flag:** `enable_export_arbitrage: bool = False` (disabled by default).
   - **Strategy:** Evaluates future forecasted export (sell/feed-in) prices against current grid import (buy) prices.
   - **Efficiency-Adjusted Hurdle Rate:**
     ```text
     Net Margin = (Round Trip Efficiency × Sell Price(export)) - Buy Price(charge) - Battery Degradation Cost
     ```
   - When $\text{Net Margin} \ge \text{min\_profit\_threshold}$ (e.g., $\ge \$0.03/\text{kWh}$), FluxEM schedules a grid-charge window at $t_{\text{charge}}$ and a matching discharge/export window at $t_{\text{export}}$.
   - Guarantees battery discharge duration matches the arbitrage charge volume while respecting minimum reserve SOC and inverter export power limits.

### D. Drift-Triggered MPC (Smart Watchdog)
Optimizes compute resources by avoiding blind 30-minute re-runs:
- **Baseline Run:** Executes a full 24-hour optimization sweep once daily (or on manual trigger).
- **Variance Watchdog:** Periodically (e.g., every 30 minutes) compares actual observed sensor data against what the forecast predicted for that exact timestamp.
- **Threshold Triggers:** Re-optimization only fires if statistical variance crosses configurable thresholds:
  - **Solar Drift:** Actual vs. forecasted output deviates by $> X\%$ (e.g., sudden cloud cover).
  - **Price Drift:** Spot prices spike or diverge unexpectedly from the pricing curve.
  - **Load Drift:** Baseline home consumption scales wildly away from expectations (evaluating pure baseline load without deferrable distortion).

## 4. Integration & Communication Flow
1. **Home Assistant Automation:** Triggers on schedule or state change, gathers raw sensor states (whole home power, individual smart plug power, solar forecast, prices), builds the JSON payload, and sends a REST/Webhook call to the microservice.
2. **Microservice Processing:**
   - Decomposes whole-home load into baseline vs. active deferrable load.
   - Checks the Drift Watchdog (decides whether to run a full re-optimization or hold the baseline plan).
   - Executes deferrable load scheduling, deficit grid pre-charging, and export arbitrage logic.
3. **MQTT Output:** Streams resulting 24-hour time-series arrays back to Home Assistant (`sensor.custom_engine_*`), which instantly maps them to virtual sensors for cards and automations.
