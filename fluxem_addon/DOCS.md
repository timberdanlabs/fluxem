# FluxEM Home Assistant Add-on ⚡

**FluxEM** is a lightweight, self-hosted energy optimization microservice engineered for Home Assistant.

## How to Configure

1. **Start the Add-on**: Click **Start** in the Add-on settings. Enable **Start on boot** and **Watchdog**.
2. **Open WebUI**: Click **Open Web UI** or access FluxEM directly in your Home Assistant sidebar via Ingress.
3. **Configure API & Credentials**:
   - Enter your Home Assistant URL (e.g., `http://homeassistant.local:8123` or `http://supervisor/core`) and a Long-Lived Access Token.
   - Map your Solar, Price, and House Power sensors with instant live autocomplete.
   - Set up your Deferrable Loads (Hot Water, Pool Pump, EV Charger, Heat Pump).
4. **Enable MQTT Publishing**:
   - Point to your Mosquitto broker (e.g. `core-mosquitto:1883`).
   - FluxEM will automatically publish Home Assistant MQTT Auto-Discovery entities and optimal switch schedules!

## Ingress Support
FluxEM includes full Ingress support, allowing direct, secure access to the configuration dashboard and live chart previews inside Home Assistant without exposing extra ports.
