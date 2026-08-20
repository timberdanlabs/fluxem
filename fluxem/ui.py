"""
FluxEM WebUI Dashboard and Configuration Interface.
Modern, responsive glassmorphism UI rendered directly by FastAPI using TailwindCSS and Alpine.js.
Supports live autocomplete from connected Home Assistant entities and real-time optimization preview.
"""

from fastapi.responses import HTMLResponse
from fluxem import __version__

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FluxEM - Energy Optimization Engine</title>
  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- Alpine.js CDN -->
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js"></script>
  <!-- Chart.js CDN -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
  <!-- FontAwesome Icons -->
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">

  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: {
              50: '#ecfdf5',
              500: '#10b981',
              600: '#059669',
              700: '#047857',
              900: '#064e3b',
            }
          }
        }
      }
    }
  </script>
  <style>
    body { background-color: #0f172a; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; }
    .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    [x-cloak] { display: none !important; }
  </style>
</head>
<body class="min-h-screen flex flex-col antialiased selection:bg-emerald-500 selection:text-white" x-data="fluxemApp()" x-init="init()" x-cloak>

  <!-- Top Navbar -->
  <header class="border-b border-slate-800 bg-slate-950/80 sticky top-0 z-40 backdrop-blur-md">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-900/40">
          <i class="fa-solid fa-bolt text-slate-950 text-lg"></i>
        </div>
        <div>
          <h1 class="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            FluxEM <span class="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">__FLUXEM_VERSION__</span>
          </h1>
          <p class="text-xs text-slate-400">Home Energy Optimization Engine</p>
        </div>
      </div>

      <!-- Action buttons -->
      <div class="flex items-center space-x-3">
        <button @click="saveConfig()" :disabled="saving" class="inline-flex items-center px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition shadow-lg shadow-emerald-900/30 disabled:opacity-50">
          <i class="fa-solid fa-floppy-disk mr-2" :class="saving ? 'animate-spin fa-spinner' : ''"></i>
          <span x-text="saving ? 'Saving...' : 'Save Configuration'"></span>
        </button>
        <a href="/docs" target="_blank" class="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium border border-slate-700 transition">
          <i class="fa-solid fa-book-open mr-1.5"></i> API Docs
        </a>
      </div>
    </div>
  </header>

  <!-- Datalists for Auto-Complete with Smart Category Filtering -->
  <datalist id="ha-solar-sensors">
    <template x-for="e in (!smartFilterEnabled || haSolarSensors.length === 0 ? haSensors : haSolarSensors)" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name + (e.unit ? ' (' + e.unit + ')' : (e.state ? ' [' + e.state + ']' : '')) + (e.has_forecast ? ' ⚡ Forecast' : '')"></option>
    </template>
  </datalist>

  <datalist id="ha-buy-price-sensors">
    <template x-for="e in (!smartFilterEnabled || haBuyPriceSensors.length === 0 ? haSensors : haBuyPriceSensors)" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name + (e.unit ? ' (' + e.unit + ')' : (e.state ? ' [' + e.state + ']' : '')) + (e.has_forecast ? ' ⚡ Tariff' : '')"></option>
    </template>
  </datalist>

  <datalist id="ha-sell-price-sensors">
    <template x-for="e in (!smartFilterEnabled || haSellPriceSensors.length === 0 ? haSensors : haSellPriceSensors)" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name + (e.unit ? ' (' + e.unit + ')' : (e.state ? ' [' + e.state + ']' : '')) + (e.has_forecast ? ' ⚡ Feed-in' : '')"></option>
    </template>
  </datalist>

  <datalist id="ha-power-sensors">
    <template x-for="e in (!smartFilterEnabled || haPowerSensors.length === 0 ? haSensors : haPowerSensors)" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name + (e.unit ? ' (' + e.unit + ')' : (e.state ? ' [' + e.state + ']' : ''))"></option>
    </template>
  </datalist>

  <datalist id="ha-battery-sensors">
    <template x-for="e in (!smartFilterEnabled || haBatterySensors.length === 0 ? haSensors : haBatterySensors)" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name + (e.unit ? ' (' + e.unit + ')' : (e.state ? ' [' + e.state + ']' : ''))"></option>
    </template>
  </datalist>

  <datalist id="ha-switches">
    <template x-for="e in haSwitches" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name + (e.state ? ' [' + e.state + ']' : '')"></option>
    </template>
  </datalist>

  <datalist id="ha-sensors">
    <template x-for="e in haSensors" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name + (e.unit ? ' (' + e.unit + ')' : '')"></option>
    </template>
  </datalist>

  <!-- Toast Notification -->
  <div x-show="toast.show" x-transition class="fixed bottom-5 right-5 z-50 max-w-md p-4 rounded-xl shadow-2xl border flex items-center space-x-3"
       :class="toast.type === 'success' ? 'bg-emerald-950/95 border-emerald-500/50 text-emerald-200' : 'bg-rose-950/95 border-rose-500/50 text-rose-200'">
    <i :class="toast.type === 'success' ? 'fa-solid fa-circle-check text-emerald-400' : 'fa-solid fa-circle-exclamation text-rose-400'" class="text-xl"></i>
    <div class="text-sm font-medium" x-text="toast.message"></div>
  </div>

  <!-- Main Container -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

    <!-- Error Alert Banner (if any) -->
    <div x-show="lastSyncError" x-transition class="mb-6 bg-rose-950/80 border border-rose-500/50 rounded-xl p-4 flex items-start justify-between text-rose-200 text-sm">
      <div class="flex items-start space-x-3">
        <i class="fa-solid fa-triangle-exclamation text-rose-400 text-lg mt-0.5"></i>
        <div>
          <div class="font-semibold text-white">Home Assistant Sync / Optimization Message</div>
          <div class="text-xs text-rose-300 font-mono mt-1 whitespace-pre-wrap" x-text="lastSyncError"></div>
        </div>
      </div>
      <button @click="lastSyncError = null" class="text-rose-400 hover:text-white p-1 transition">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <!-- Navigation Tabs -->
    <div class="flex space-x-2 border-b border-slate-800 pb-3 mb-8 overflow-x-auto">
      <button @click="switchTab('ha')" :class="activeTab === 'ha' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-transparent'" class="px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center space-x-2 whitespace-nowrap">
        <i class="fa-solid fa-house-signal"></i>
        <span>Home Assistant API</span>
      </button>

      <button @click="switchTab('loads')" :class="activeTab === 'loads' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-transparent'" class="px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center space-x-2 whitespace-nowrap">
        <i class="fa-solid fa-sliders"></i>
        <span>Deferrable Loads</span>
        <span class="ml-1.5 px-1.5 py-0.5 rounded-full text-xs bg-slate-800 text-slate-300 font-mono" x-text="config.deferrable_loads.length"></span>
      </button>

      <button @click="switchTab('battery')" :class="activeTab === 'battery' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-transparent'" class="px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center space-x-2 whitespace-nowrap">
        <i class="fa-solid fa-car-battery"></i>
        <span>Battery Storage</span>
      </button>

      <button @click="switchTab('arbitrage')" :class="activeTab === 'arbitrage' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-transparent'" class="px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center space-x-2 whitespace-nowrap">
        <i class="fa-solid fa-arrow-trend-up"></i>
        <span>Grid Arbitrage & Export</span>
      </button>

      <button @click="switchTab('watchdog')" :class="activeTab === 'watchdog' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-transparent'" class="px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center space-x-2 whitespace-nowrap">
        <i class="fa-solid fa-shield-dog"></i>
        <span>Drift Watchdog</span>
      </button>

      <button @click="switchTab('mqtt')" :class="activeTab === 'mqtt' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-transparent'" class="px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center space-x-2 whitespace-nowrap">
        <i class="fa-solid fa-network-wired"></i>
        <span>MQTT Broker</span>
      </button>

      <button @click="switchTab('preview')" :class="activeTab === 'preview' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-transparent'" class="px-4 py-2 rounded-lg text-sm font-medium border transition flex items-center space-x-2 whitespace-nowrap">
        <i class="fa-solid fa-chart-line"></i>
        <span>Preview & Simulation</span>
      </button>
    </div>

    <!-- TAB 0: HOME ASSISTANT DIRECT API -->
    <div x-show="activeTab === 'ha'" class="space-y-6 max-w-4xl">
      <div>
        <h2 class="text-lg font-semibold text-white">Direct Home Assistant API Connection</h2>
        <p class="text-sm text-slate-400">Connect directly to Home Assistant with a Long-Lived Access Token to auto-discover entities and fetch live forecasts with zero YAML.</p>
      </div>

      <div class="glass p-6 rounded-xl space-y-6">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 text-sm">
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Home Assistant URL / IP</label>
            <input type="text" x-model="config.ha_url" placeholder="http://192.168.1.100:8123" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
            <span class="text-xs text-slate-500 mt-1 block">Use LAN IP or homeassistant.local. (If in Docker, do not use localhost).</span>
          </div>
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Long-Lived Access Token</label>
            <input type="password" x-model="config.ha_token" placeholder="eyJhbGciOi..." class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
            <span class="text-xs text-slate-500 mt-1 block">Created in HA under Profile &gt; Long-Lived Access Tokens.</span>
          </div>
        </div>

        <div class="flex items-center justify-between pt-3 border-t border-slate-800">
          <div class="flex items-center space-x-3">
            <button @click="testHaConnection()" :disabled="testingHa" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700 text-sm font-medium transition disabled:opacity-50">
              <i class="fa-solid fa-plug mr-1.5" :class="testingHa ? 'animate-spin fa-spinner' : ''"></i> Test HA Connection
            </button>

            <button @click="syncAndOptimize()" :disabled="syncingHa" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition disabled:opacity-50">
              <i class="fa-solid fa-rotate mr-1.5" :class="syncingHa ? 'animate-spin fa-spinner' : ''"></i> Pull Sensors & Optimize Now
            </button>
          </div>

          <!-- Entity count pill -->
          <div class="hidden sm:flex items-center space-x-2 text-xs text-slate-400">
            <i class="fa-solid fa-wand-magic-sparkles text-emerald-400"></i>
            <span>Autocomplete:</span>
            <span class="font-mono text-emerald-400" x-text="haEntities.length + ' entities'"></span>
            <button @click="loadHaEntities(true)" :disabled="loadingEntities" class="text-slate-400 hover:text-emerald-300 p-1" title="Refresh entity list">
              <i class="fa-solid fa-arrows-rotate" :class="loadingEntities ? 'animate-spin' : ''"></i>
            </button>
          </div>
        </div>
      </div>

      <!-- Timezone and Alignment Settings -->
      <div class="glass p-6 rounded-xl space-y-5">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="font-semibold text-white text-base flex items-center gap-2">
              <i class="fa-solid fa-earth-americas text-emerald-400"></i> Timezone & Offset Alignment
            </h3>
            <p class="text-xs text-slate-400">Normalizes UTC (Solcast, HA History) and local offset forecasts (Amber, Tibber) into your local solar day.</p>
          </div>
          <span class="text-xs px-2.5 py-1 rounded bg-slate-900 border border-slate-700 text-emerald-400 font-mono" x-show="detectedTimezone">
            Detected: <span x-text="detectedTimezone"></span>
          </span>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div>
            <label class="block text-slate-400 mb-1 font-medium">Home Assistant Timezone</label>
            <select x-model="config.ha_timezone" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:border-emerald-500 focus:outline-none">
              <option value="auto">Auto-detect from Home Assistant</option>
              <option value="Australia/Sydney">Australia/Sydney (AEST/AEDT, UTC+10/+11)</option>
              <option value="Australia/Melbourne">Australia/Melbourne (AEST/AEDT, UTC+10/+11)</option>
              <option value="Australia/Brisbane">Australia/Brisbane (AEST, UTC+10 no DST)</option>
              <option value="Australia/Adelaide">Australia/Adelaide (ACST/ACDT, UTC+9:30/+10:30)</option>
              <option value="Australia/Perth">Australia/Perth (AWST, UTC+8)</option>
              <option value="Australia/Hobart">Australia/Hobart (AEST/AEDT)</option>
              <option value="Australia/Darwin">Australia/Darwin (ACST, UTC+9:30)</option>
              <option value="Europe/London">Europe/London (GMT/BST)</option>
              <option value="Europe/Berlin">Europe/Berlin (CET/CEST)</option>
              <option value="Europe/Amsterdam">Europe/Amsterdam (CET/CEST)</option>
              <option value="America/New_York">America/New_York (EST/EDT)</option>
              <option value="America/Chicago">America/Chicago (CST/CDT)</option>
              <option value="America/Denver">America/Denver (MST/MDT)</option>
              <option value="America/Los_Angeles">America/Los_Angeles (PST/PDT)</option>
              <option value="UTC">UTC (Coordinated Universal Time)</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Entity Mappings with Autocomplete -->
      <div class="glass p-6 rounded-xl space-y-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="font-semibold text-white text-base">Sensor Entity Mappings</h3>
            <p class="text-xs text-slate-400">Type or pick from dropdown. Smart class filters auto-hide non-relevant sensors (e.g. 3D printers, lights, door sensors).</p>
          </div>
          <div class="flex items-center space-x-3">
            <label class="flex items-center space-x-1.5 cursor-pointer text-xs text-slate-300 bg-slate-800/80 px-2.5 py-1 rounded-lg border border-slate-700 hover:border-slate-600 transition">
              <input type="checkbox" x-model="smartFilterEnabled" class="rounded bg-slate-900 border-slate-600 text-emerald-500 focus:ring-0">
              <i class="fa-solid fa-filter text-emerald-400 text-[11px]"></i>
              <span>Smart Class Filter</span>
            </label>
            <button type="button" @click="loadHaEntities(true)" :disabled="loadingEntities" class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs border border-slate-700 transition flex items-center space-x-1">
              <i class="fa-solid fa-rotate" :class="loadingEntities ? 'animate-spin' : ''"></i>
              <span>Reload Entities</span>
            </button>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="block text-slate-400 font-medium">Solar Forecast Entity (Solcast / Forecast.Solar)</label>
              <span class="text-[11px] text-emerald-400 font-mono" x-show="smartFilterEnabled && haSolarSensors.length > 0" x-text="haSolarSensors.length + ' solar entities'"></span>
            </div>
            <input type="text" list="ha-solar-sensors" x-model="config.ha_entity_mappings.solar_forecast_entity" placeholder="sensor.solcast_pv_forecast" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="block text-slate-400 font-medium">Electricity Buy Price Forecast (Amber / Tibber / Nordpool)</label>
              <span class="text-[11px] text-amber-400 font-mono" x-show="smartFilterEnabled && haBuyPriceSensors.length > 0" x-text="haBuyPriceSensors.length + ' price entities'"></span>
            </div>
            <input type="text" list="ha-buy-price-sensors" x-model="config.ha_entity_mappings.buy_price_forecast_entity" placeholder="sensor.amber_general_forecast" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="block text-slate-400 font-medium">Feed-in / Export Price Forecast</label>
              <span class="text-[11px] text-cyan-400 font-mono" x-show="smartFilterEnabled && haSellPriceSensors.length > 0" x-text="haSellPriceSensors.length + ' export entities'"></span>
            </div>
            <input type="text" list="ha-sell-price-sensors" x-model="config.ha_entity_mappings.sell_price_forecast_entity" placeholder="sensor.amber_feed_in_forecast" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="block text-slate-400 font-medium">Whole-House Power Sensor (Watts / kW)</label>
              <span class="text-[11px] text-indigo-400 font-mono" x-show="smartFilterEnabled && haPowerSensors.length > 0" x-text="haPowerSensors.length + ' power meters'"></span>
            </div>
            <input type="text" list="ha-power-sensors" x-model="config.ha_entity_mappings.house_power_entity" placeholder="sensor.power_meter_house" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="block text-slate-400 font-medium">Battery State of Charge (%)</label>
              <span class="text-[11px] text-emerald-400 font-mono" x-show="smartFilterEnabled && haBatterySensors.length > 0" x-text="haBatterySensors.length + ' battery entities'"></span>
            </div>
            <input type="text" list="ha-battery-sensors" x-model="config.ha_entity_mappings.battery_soc_entity" placeholder="sensor.battery_state_of_charge" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>
        </div>
      </div>

      <!-- Lookahead Horizon & Historical Load Forecasting Settings -->
      <div class="glass p-6 rounded-xl space-y-5">
        <h3 class="font-semibold text-white text-base flex items-center gap-2">
          <i class="fa-solid fa-calendar-days text-emerald-400"></i> Lookahead Horizon & Historical Load Forecasting
        </h3>
        <p class="text-xs text-slate-400">Configure how far into the future FluxEM plans (up to 3 days), and how many past days of whole-house load history are analyzed.</p>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 text-sm">
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Optimization Lookahead Horizon (Days)</label>
            <div class="grid grid-cols-3 gap-2">
              <button type="button" @click="config.prediction_horizon_days = 1" :class="config.prediction_horizon_days === 1 ? 'bg-emerald-600 text-white border-emerald-500 font-semibold' : 'bg-slate-900 text-slate-400 border-slate-700 hover:text-white'" class="py-2 px-3 rounded-lg border text-center text-xs transition">
                1 Day (24h)
              </button>
              <button type="button" @click="config.prediction_horizon_days = 2" :class="config.prediction_horizon_days === 2 ? 'bg-emerald-600 text-white border-emerald-500 font-semibold' : 'bg-slate-900 text-slate-400 border-slate-700 hover:text-white'" class="py-2 px-3 rounded-lg border text-center text-xs transition">
                2 Days (48h)
              </button>
              <button type="button" @click="config.prediction_horizon_days = 3" :class="config.prediction_horizon_days === 3 ? 'bg-emerald-600 text-white border-emerald-500 font-semibold' : 'bg-slate-900 text-slate-400 border-slate-700 hover:text-white'" class="py-2 px-3 rounded-lg border text-center text-xs transition">
                3 Days (72h)
              </button>
            </div>
            <span class="text-xs text-slate-500 mt-1 block">Maximum 3 days lookahead.</span>
          </div>

          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Historical Days for Load Forecast (1 - 14 Days)</label>
            <div class="flex items-center space-x-3">
              <input type="range" min="1" max="14" step="1" x-model.number="config.load_history_days" class="w-full accent-emerald-500">
              <span class="font-mono font-bold text-emerald-400 text-base w-14 text-right" x-text="config.load_history_days + 'd'"></span>
            </div>
            <span class="text-xs text-slate-500 mt-1 block">Days of past consumption history queried from Home Assistant.</span>
          </div>

          <div class="sm:col-span-2">
            <label class="block text-slate-300 mb-1.5 font-medium">Historical Load Forecasting Method</label>
            <select x-model="config.load_forecast_method" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none text-xs">
              <option value="moving_average">Time-of-Day Moving Average (Smooth past N days pattern)</option>
              <option value="median_profile">Median Daily Profile (Resistant to past unusual load spikes)</option>
            </select>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 1: DEFERRABLE LOADS -->
    <div x-show="activeTab === 'loads'" class="space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-semibold text-white">Controllable Deferrable Loads</h2>
          <p class="text-sm text-slate-400">Configure appliances like hot water systems, pool pumps, and EV chargers.</p>
        </div>
        <button @click="addLoad()" class="inline-flex items-center px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700 text-sm font-medium transition">
          <i class="fa-solid fa-plus mr-1.5"></i> Add Load
        </button>
      </div>

      <!-- Zero-Helper house_power toggle -->
      <div class="glass p-4 rounded-xl flex items-center justify-between">
        <div>
          <div class="font-medium text-white text-sm">Automatic Zero-Helper Deferrable Deduction</div>
          <div class="text-xs text-slate-400">Automatically subtracts active load consumption from whole-house power sensor without custom template sensors.</div>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" x-model="config.deduct_deferrable_loads_from_house_power" class="sr-only peer">
          <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>

      <!-- Empty state -->
      <template x-if="config.deferrable_loads.length === 0">
        <div class="glass rounded-xl p-12 text-center text-slate-400">
          <i class="fa-solid fa-plug text-4xl mb-3 text-slate-600"></i>
          <p class="text-base font-medium text-slate-300">No deferrable loads configured yet</p>
          <p class="text-sm text-slate-500 mb-4">Add your hot water system, pool pump, or EV charger to let FluxEM optimize runtimes.</p>
          <button @click="addLoad()" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition">
            Add First Load
          </button>
        </div>
      </template>

      <!-- Loads Grid -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <template x-for="(load, index) in config.deferrable_loads" :key="index">
          <div class="glass rounded-xl p-5 space-y-4 border border-slate-800 hover:border-slate-700 transition">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3">
              <div class="flex items-center space-x-2 flex-wrap gap-y-1">
                <i :class="load.critical ? 'fa-solid fa-fire-flame-curved text-rose-400' : (load.solar_only ? 'fa-solid fa-sun text-amber-400' : 'fa-solid fa-leaf text-indigo-400')"></i>
                <span class="font-semibold text-white" x-text="load.name || load.id || 'New Load'"></span>
                <span class="text-xs px-2 py-0.5 rounded font-mono" :class="load.critical ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' : (load.solar_only ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20')" x-text="load.critical ? 'Critical (Mandatory)' : (load.solar_only ? 'Solar Only' : 'Opportunistic')"></span>
                <span class="text-xs px-2 py-0.5 rounded font-mono" :class="load.continuous ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20' : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'" x-text="load.continuous ? 'Continuous' : 'Flexible'"></span>
                <span x-show="load.complete_on_cutoff" class="text-xs px-2 py-0.5 rounded font-mono bg-teal-500/10 text-teal-400 border border-teal-500/20" title="Auto-detects thermostat cutoff">Thermostat Cutoff</span>
              </div>
              <button @click="removeLoad(index)" class="text-slate-500 hover:text-rose-400 transition p-1">
                <i class="fa-solid fa-trash-can"></i>
              </button>
            </div>

            <div class="grid grid-cols-2 gap-3 text-xs">
              <div>
                <label class="block text-slate-400 mb-1">Load ID (Unique)</label>
                <input type="text" x-model="load.id" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
              </div>
              <div>
                <label class="block text-slate-400 mb-1">Friendly Label</label>
                <input type="text" x-model="load.name" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white focus:border-emerald-500 focus:outline-none">
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Nominal Power (Watts)</label>
                <input type="number" x-model.number="load.nominal_power_w" step="100" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white focus:border-emerald-500 focus:outline-none">
              </div>
              <div>
                <label class="block text-slate-400 mb-1">Daily Target (Hours)</label>
                <input type="number" x-model.number="load.required_hours" step="0.5" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white focus:border-emerald-500 focus:outline-none">
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Window Start (e.g. 08:00)</label>
                <input type="text" x-model="load.window_start_time" placeholder="Optional" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
              </div>
              <div>
                <label class="block text-slate-400 mb-1">Window End (e.g. 18:00)</label>
                <input type="text" x-model="load.window_end_time" placeholder="Optional" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
              </div>

              <div>
                <label class="block text-slate-400 mb-1">HA Power Sensor (Optional)</label>
                <input type="text" list="ha-power-sensors" x-model="load.power_sensor_entity_id" placeholder="sensor.water_heater_power" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
              </div>
              <div>
                <label class="block text-slate-400 mb-1">HA Switch Entity (Optional)</label>
                <input type="text" list="ha-switches" x-model="load.switch_entity_id" placeholder="switch.water_heater" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
              </div>

              <!-- Opportunistic / Critical Configuration Section -->
              <div class="col-span-2 pt-2 border-t border-slate-800/60 grid grid-cols-2 gap-3 bg-slate-950/40 p-2.5 rounded-lg">
                <div class="col-span-2 flex items-center justify-between">
                  <label class="flex items-center space-x-2 cursor-pointer">
                    <input type="checkbox" x-model="load.critical" class="rounded bg-slate-900 border-slate-700 text-rose-500 focus:ring-0">
                    <span class="font-medium text-white">Critical Load (Mandatory Daily Run)</span>
                  </label>
                  <span class="text-[11px] text-slate-400" x-text="load.critical ? 'Runs every day (uses grid if needed)' : 'Can skip on expensive/cloudy days'"></span>
                </div>

                <template x-if="!load.critical">
                  <div class="contents">
                    <div>
                      <label class="block text-slate-400 mb-1">Max Skip Days (0-7)</label>
                      <input type="number" x-model.number="load.max_skip_days" min="0" max="7" placeholder="1" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white focus:border-emerald-500 focus:outline-none">
                      <span class="text-[10px] text-slate-500">Max days to defer before forcing run</span>
                    </div>
                    <div>
                      <label class="block text-slate-400 mb-1">Max Grid Price ($/kWh)</label>
                      <input type="number" x-model.number="load.max_buy_price" step="0.01" placeholder="e.g. 0.20" class="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-white focus:border-emerald-500 focus:outline-none">
                      <span class="text-[10px] text-slate-500">Only run on grid if price is below this</span>
                    </div>
                    <div class="col-span-2 flex items-center justify-between pt-1">
                      <label class="flex items-center space-x-2 cursor-pointer">
                        <input type="checkbox" x-model="load.solar_only" class="rounded bg-slate-900 border-slate-700 text-amber-500 focus:ring-0">
                        <span>Solar Only (Zero Grid Import)</span>
                      </label>
                      <div class="flex items-center space-x-1.5">
                        <span class="text-[11px] text-slate-400">Prior Skips:</span>
                        <input type="number" x-model.number="load.consecutive_days_skipped" min="0" class="w-12 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-center text-white text-[11px]">
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </div>

            <!-- Toggles for continuous, cutoff & inclusion -->
            <div class="pt-2 border-t border-slate-800/80 grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs text-slate-300">
              <label class="flex items-center space-x-2 cursor-pointer">
                <input type="checkbox" x-model="load.continuous" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0">
                <span>Continuous Block</span>
              </label>

              <label class="flex items-center space-x-2 cursor-pointer" title="Automatically considers daily quota satisfied when power drops to 0W after an active heating cycle (internal thermostat reached temperature)">
                <input type="checkbox" x-model="load.complete_on_cutoff" class="rounded bg-slate-900 border-slate-700 text-teal-500 focus:ring-0">
                <span>Thermostat Cutoff</span>
              </label>

              <label class="flex items-center space-x-2 cursor-pointer">
                <input type="checkbox" x-model="load.is_included_in_total_load" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0">
                <span>In Whole-House Power</span>
              </label>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- TAB 2: BATTERY STORAGE -->
    <div x-show="activeTab === 'battery'" class="space-y-6 max-w-3xl">
      <div>
        <h2 class="text-lg font-semibold text-white">Home Battery System Specs</h2>
        <p class="text-sm text-slate-400">Configure your default battery capacity, operational bounds, and charging power rates.</p>
      </div>

      <div class="glass p-6 rounded-xl space-y-5">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 text-sm">
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Usable Capacity (kWh)</label>
            <input type="number" x-model.number="battery.capacity_kwh" step="0.5" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Default / Target SOC (%)</label>
            <input type="number" x-model.number="battery.soc_percent" step="5" min="0" max="100" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>

          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Max Charge Power (Watts)</label>
            <input type="number" x-model.number="battery.max_charge_power_w" step="500" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Max Discharge Power (Watts)</label>
            <input type="number" x-model.number="battery.max_discharge_power_w" step="500" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>

          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Min SOC Reserve (%)</label>
            <input type="number" x-model.number="battery.min_soc_percent" step="5" min="0" max="100" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Max Target SOC (%)</label>
            <input type="number" x-model.number="battery.max_soc_percent" step="5" min="0" max="100" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>

          <div class="sm:col-span-2">
            <label class="block text-slate-300 mb-1.5 font-medium">Round-Trip Efficiency (0.0 to 1.0)</label>
            <input type="number" x-model.number="battery.round_trip_efficiency" step="0.01" min="0.5" max="1.0" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
            <span class="text-xs text-slate-500 mt-1 block">e.g. 0.90 for 90% round trip efficiency (LiFePO4 / Tesla Powerwall).</span>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: ARBITRAGE & EXPORT -->
    <div x-show="activeTab === 'arbitrage'" class="space-y-6 max-w-3xl">
      <div>
        <h2 class="text-lg font-semibold text-white">Dynamic Feed-in Export Arbitrage</h2>
        <p class="text-sm text-slate-400">Enable opportunistic grid pre-charging when feed-in prices are projected to spike higher than purchase costs.</p>
      </div>

      <div class="glass p-6 rounded-xl space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <div class="font-medium text-white text-base">Enable Export Arbitrage Mode</div>
            <div class="text-xs text-slate-400">Optional trading mode: charges battery from grid during cheap rates to export during price spikes.</div>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" x-model="config.enable_export_arbitrage" class="sr-only peer">
            <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
          </label>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 text-sm pt-4 border-t border-slate-800">
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Minimum Profit Hurdle ($/kWh)</label>
            <input type="number" x-model.number="config.min_arbitrage_profit_per_kwh" step="0.01" min="0" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
            <span class="text-xs text-slate-500 mt-1 block">Required spread above purchase & wear costs before arbitrage triggers.</span>
          </div>

          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Battery Degradation Wear Cost ($/kWh)</label>
            <input type="number" x-model.number="config.battery_degradation_cost_per_kwh" step="0.005" min="0" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
            <span class="text-xs text-slate-500 mt-1 block">Cost accounting for battery cell wear per cycled kWh.</span>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 4: WATCHDOG THRESHOLDS -->
    <div x-show="activeTab === 'watchdog'" class="space-y-6 max-w-3xl">
      <div>
        <h2 class="text-lg font-semibold text-white">Drift Watchdog Sensitivity</h2>
        <p class="text-sm text-slate-400">Configure statistical variance thresholds before FluxEM triggers schedule re-optimization.</p>
      </div>

      <div class="glass p-6 rounded-xl space-y-6">
        <div>
          <div class="flex justify-between text-sm mb-1.5">
            <span class="text-slate-300 font-medium">Solar Generation Drift Tolerance</span>
            <span class="font-mono text-emerald-400" x-text="config.solar_drift_threshold_pct + '%'"></span>
          </div>
          <input type="range" min="5" max="60" step="5" x-model.number="config.solar_drift_threshold_pct" class="w-full accent-emerald-500">
        </div>

        <div>
          <div class="flex justify-between text-sm mb-1.5">
            <span class="text-slate-300 font-medium">Electricity Buy Price Drift Tolerance</span>
            <span class="font-mono text-emerald-400" x-text="config.price_drift_threshold_pct + '%'"></span>
          </div>
          <input type="range" min="5" max="50" step="5" x-model.number="config.price_drift_threshold_pct" class="w-full accent-emerald-500">
        </div>

        <div>
          <div class="flex justify-between text-sm mb-1.5">
            <span class="text-slate-300 font-medium">Household Baseline Load Drift Tolerance</span>
            <span class="font-mono text-emerald-400" x-text="config.load_drift_threshold_pct + '%'"></span>
          </div>
          <input type="range" min="5" max="60" step="5" x-model.number="config.load_drift_threshold_pct" class="w-full accent-emerald-500">
        </div>
      </div>
    </div>

    <!-- TAB 5: MQTT SETTINGS -->
    <div x-show="activeTab === 'mqtt'" class="space-y-6 max-w-3xl">
      <div>
        <h2 class="text-lg font-semibold text-white">MQTT Broker & Home Assistant Auto-Discovery</h2>
        <p class="text-sm text-slate-400">Configure real-time publishing of schedule curves and switch commands.</p>
      </div>

      <div class="glass p-6 rounded-xl space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <div class="font-medium text-white text-base">Enable MQTT Publishing</div>
            <div class="text-xs text-slate-400">Publishes power schedules and switch states directly to Home Assistant MQTT.</div>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" x-model="config.mqtt_enabled" class="sr-only peer">
            <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
          </label>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 text-sm pt-4 border-t border-slate-800">
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Broker Host</label>
            <input type="text" x-model="config.mqtt_broker_host" placeholder="localhost" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Broker Port</label>
            <input type="number" x-model.number="config.mqtt_broker_port" placeholder="1883" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>

          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Username (Optional)</label>
            <input type="text" x-model="config.mqtt_username" placeholder="Optional" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>
          <div>
            <label class="block text-slate-300 mb-1.5 font-medium">Password (Optional)</label>
            <input type="password" x-model="config.mqtt_password" placeholder="Optional" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white focus:border-emerald-500 focus:outline-none">
          </div>

          <div class="sm:col-span-2">
            <label class="block text-slate-300 mb-1.5 font-medium">Topic Prefix</label>
            <input type="text" x-model="config.mqtt_topic_prefix" placeholder="fluxem" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
          </div>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-slate-800">
          <div class="flex items-center space-x-3">
            <button @click="testMqttConnection()" :disabled="testingMqtt" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700 text-sm font-medium transition disabled:opacity-50 flex items-center">
              <i class="fa-solid fa-network-wired mr-1.5" :class="testingMqtt ? 'animate-spin fa-spinner' : ''"></i>
              <span x-text="testingMqtt ? 'Testing...' : 'Test MQTT Connection'"></span>
            </button>

            <button @click="saveConfig()" :disabled="saving" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition disabled:opacity-50 flex items-center">
              <i class="fa-solid fa-floppy-disk mr-1.5" :class="saving ? 'animate-spin fa-spinner' : ''"></i>
              <span>Save MQTT Settings</span>
            </button>
          </div>

          <div x-show="mqttStatusMessage" class="text-xs font-mono px-3 py-1.5 rounded-lg border" :class="mqttConnected ? 'bg-emerald-950/80 border-emerald-500/40 text-emerald-300' : 'bg-rose-950/80 border-rose-500/40 text-rose-300'" x-text="mqttStatusMessage"></div>
        </div>
      </div>
    </div>

    <!-- TAB 6: PREVIEW & SIMULATION -->
    <div x-show="activeTab === 'preview'" class="space-y-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold text-white">Interactive Optimization Schedule Preview</h2>
          <p class="text-sm text-slate-400">View real-time or simulated power curves, expected battery SOC %, and step-by-step dispatch across the horizon.</p>
        </div>
        <div class="flex items-center space-x-3">
          <button @click="syncAndOptimize()" :disabled="syncingHa" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition disabled:opacity-50 flex items-center">
            <i class="fa-solid fa-rotate mr-1.5" :class="syncingHa ? 'animate-spin fa-spinner' : ''"></i> Pull & Re-Optimize
          </button>
          <button @click="runSimulation()" :disabled="simulating" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-sm font-medium transition disabled:opacity-50">
            <i class="fa-solid fa-play mr-1.5" :class="simulating ? 'animate-spin fa-spinner' : ''"></i> Test Simulation
          </button>
        </div>
      </div>

      <!-- Quick Metric KPI Cards -->
      <template x-if="latestSchedule">
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <div class="glass p-4 rounded-xl text-center">
            <div class="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Start / Target SOC</div>
            <div class="text-lg font-bold text-emerald-400 mt-1 font-mono">
              <span x-text="latestSchedule.battery_soc_percent && latestSchedule.battery_soc_percent.length > 0 ? latestSchedule.battery_soc_percent[0].toFixed(0) + '%' : (battery.soc_percent + '%')"></span>
              <span class="text-xs text-slate-500 font-normal"> / </span>
              <span class="text-xs text-slate-300" x-text="(latestSchedule.battery_soc_percent && latestSchedule.battery_soc_percent.length > 0 ? latestSchedule.battery_soc_percent[latestSchedule.battery_soc_percent.length-1].toFixed(0) + '%' : '--')"></span>
            </div>
          </div>

          <div class="glass p-4 rounded-xl text-center">
            <div class="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Min / Max SOC</div>
            <div class="text-lg font-bold text-teal-400 mt-1 font-mono">
              <span x-text="latestSchedule.battery_soc_percent && latestSchedule.battery_soc_percent.length > 0 ? Math.min(...latestSchedule.battery_soc_percent).toFixed(0) + '%' : '--'"></span>
              <span class="text-xs text-slate-500 font-normal"> - </span>
              <span x-text="latestSchedule.battery_soc_percent && latestSchedule.battery_soc_percent.length > 0 ? Math.max(...latestSchedule.battery_soc_percent).toFixed(0) + '%' : '--'"></span>
            </div>
          </div>

          <div class="glass p-4 rounded-xl text-center">
            <div class="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Solar Forecast</div>
            <div class="text-lg font-bold text-amber-400 mt-1 font-mono">
              <span x-text="(latestSchedule.summary?.forecast_summary?.total_solar_kwh !== undefined ? latestSchedule.summary.forecast_summary.total_solar_kwh : 0) + ' kWh'"></span>
            </div>
          </div>

          <div class="glass p-4 rounded-xl text-center">
            <div class="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Baseline Load</div>
            <div class="text-lg font-bold text-sky-400 mt-1 font-mono">
              <span x-text="(latestSchedule.summary?.forecast_summary?.total_load_kwh !== undefined ? latestSchedule.summary.forecast_summary.total_load_kwh : 0) + ' kWh'"></span>
            </div>
          </div>

          <div class="glass p-4 rounded-xl text-center">
            <div class="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Net Deficit</div>
            <div class="text-lg font-bold text-rose-400 mt-1 font-mono">
              <span x-text="(latestSchedule.summary?.forecast_summary?.net_deficit_kwh !== undefined ? latestSchedule.summary.forecast_summary.net_deficit_kwh : 0) + ' kWh'"></span>
            </div>
          </div>

          <div class="glass p-4 rounded-xl text-center">
            <div class="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Avg Buy Price</div>
            <div class="text-lg font-bold text-purple-400 mt-1 font-mono">
              <span x-text="'$' + (latestSchedule.summary?.forecast_summary?.avg_buy_price !== undefined ? latestSchedule.summary.forecast_summary.avg_buy_price : 0) + '/kWh'"></span>
            </div>
          </div>
        </div>
      </template>

      <!-- Interactive Chart with Dual Axes -->
      <div class="glass p-6 rounded-xl space-y-4">
        <div class="flex items-center justify-between text-xs text-slate-400 border-b border-slate-800 pb-3">
          <div class="flex items-center space-x-2">
            <i class="fa-solid fa-chart-line text-emerald-400"></i>
            <span class="font-medium text-slate-200">Power & Battery Trajectory Curves</span>
          </div>
          <div class="text-slate-400">Left: <span class="text-slate-300 font-mono">Watts</span> | Right: <span class="text-emerald-400 font-mono">Battery SOC %</span></div>
        </div>
        <div class="h-96 w-full relative">
          <canvas id="scheduleChart"></canvas>
        </div>
      </div>

      <!-- Step-by-Step Schedule Data Table -->
      <template x-if="latestSchedule && latestSchedule.timestamps">
        <div class="glass p-6 rounded-xl space-y-4">
          <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
              <h3 class="font-semibold text-white text-base flex items-center gap-2">
                <i class="fa-solid fa-table-list text-emerald-400"></i> Scheduled Dispatch & Expected Battery SOC Breakdown
              </h3>
              <p class="text-xs text-slate-400">Interval-by-interval power routing, expected battery state-of-charge %, and pricing.</p>
            </div>
            <span class="text-xs px-2.5 py-1 rounded bg-slate-900 border border-slate-700 text-slate-300 font-mono" x-text="latestSchedule.timestamps.length + ' timesteps'"></span>
          </div>

          <div class="overflow-x-auto max-h-96 overflow-y-auto border border-slate-800 rounded-lg">
            <table class="w-full text-left text-xs font-mono text-slate-300">
              <thead class="bg-slate-900 text-slate-400 uppercase tracking-wider sticky top-0 border-b border-slate-800">
                <tr>
                  <th class="px-3.5 py-2.5">Time</th>
                  <th class="px-3.5 py-2.5">Solar (W)</th>
                  <th class="px-3.5 py-2.5">Base Load (W)</th>
                  <th class="px-3.5 py-2.5">Def. Loads (W)</th>
                  <th class="px-3.5 py-2.5">Battery Power (W)</th>
                  <th class="px-3.5 py-2.5 text-center">Expected SOC %</th>
                  <th class="px-3.5 py-2.5">Net Grid Flow (W)</th>
                  <th class="px-3.5 py-2.5">Buy Price</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-800/60 bg-slate-950/40">
                <template x-for="(ts, idx) in latestSchedule.timestamps" :key="idx">
                  <tr class="hover:bg-slate-800/40 transition">
                    <td class="px-3.5 py-2 text-slate-300 whitespace-nowrap" x-text="formatTimeLabel(ts)"></td>
                    <td class="px-3.5 py-2 text-amber-400" x-text="Math.round(latestSchedule.solar_forecast_w[idx] || 0) + ' W'"></td>
                    <td class="px-3.5 py-2 text-sky-400" x-text="Math.round(latestSchedule.baseline_load_w[idx] || 0) + ' W'"></td>
                    <td class="px-3.5 py-2 text-pink-400" x-text="getStepDeferrablePower(idx) + ' W'"></td>
                    <td class="px-3.5 py-2 whitespace-nowrap">
                      <template x-if="latestSchedule.battery_power_w && latestSchedule.battery_power_w[idx] > 10">
                        <span class="text-emerald-400 font-semibold" x-text="'+' + Math.round(latestSchedule.battery_power_w[idx]) + ' W (Chg)'"></span>
                      </template>
                      <template x-if="latestSchedule.battery_power_w && latestSchedule.battery_power_w[idx] < -10">
                        <span class="text-purple-400 font-semibold" x-text="Math.round(latestSchedule.battery_power_w[idx]) + ' W (Dchg)'"></span>
                      </template>
                      <template x-if="!latestSchedule.battery_power_w || Math.abs(latestSchedule.battery_power_w[idx]) <= 10">
                        <span class="text-slate-500">0 W</span>
                      </template>
                    </td>
                    <td class="px-3.5 py-2 text-center whitespace-nowrap">
                      <template x-if="latestSchedule.battery_soc_percent && latestSchedule.battery_soc_percent[idx] !== undefined">
                        <span class="px-2 py-0.5 rounded font-bold"
                              :class="latestSchedule.battery_soc_percent[idx] >= 50 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : (latestSchedule.battery_soc_percent[idx] >= 20 ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20')"
                              x-text="latestSchedule.battery_soc_percent[idx].toFixed(1) + '%'">
                        </span>
                      </template>
                      <template x-if="!latestSchedule.battery_soc_percent || latestSchedule.battery_soc_percent[idx] === undefined">
                        <span class="text-slate-600">--</span>
                      </template>
                    </td>
                    <td class="px-3.5 py-2 whitespace-nowrap">
                      <template x-if="latestSchedule.grid_import_power_w && latestSchedule.grid_import_power_w[idx] > 10">
                        <span class="text-rose-400" x-text="'+' + Math.round(latestSchedule.grid_import_power_w[idx]) + ' W (Import)'"></span>
                      </template>
                      <template x-if="latestSchedule.grid_export_power_w && latestSchedule.grid_export_power_w[idx] > 10">
                        <span class="text-emerald-400" x-text="'-' + Math.round(latestSchedule.grid_export_power_w[idx]) + ' W (Export)'"></span>
                      </template>
                      <template x-if="(!latestSchedule.grid_import_power_w || latestSchedule.grid_import_power_w[idx] <= 10) && (!latestSchedule.grid_export_power_w || latestSchedule.grid_export_power_w[idx] <= 10)">
                        <span class="text-slate-500">0 W</span>
                      </template>
                    </td>
                    <td class="px-3.5 py-2 text-slate-300" x-text="'$' + (latestSchedule.buy_prices && latestSchedule.buy_prices[idx] !== undefined ? latestSchedule.buy_prices[idx].toFixed(3) : '0.000')"></td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>

  </main>

  <!-- Application Logic -->
  <script>
    function fluxemApp() {
      return {
        activeTab: 'ha',
        saving: false,
        simulating: false,
        testingHa: false,
        testingMqtt: false,
        mqttConnected: false,
        mqttStatusMessage: '',
        syncingHa: false,
        loadingEntities: false,
        lastSyncError: null,
        latestSchedule: null,
        detectedTimezone: '',
        toast: { show: false, message: '', type: 'success' },
        smartFilterEnabled: true,
        haEntities: [],
        haSensors: [],
        haSwitches: [],
        haSolarSensors: [],
        haBuyPriceSensors: [],
        haSellPriceSensors: [],
        haPowerSensors: [],
        haBatterySensors: [],
        config: {
          default_timestep_minutes: 30,
          prediction_horizon_days: 1,
          load_history_days: 3,
          load_forecast_method: 'moving_average',
          deduct_deferrable_loads_from_house_power: true,
          deferrable_loads: [],
          enable_export_arbitrage: false,
          min_arbitrage_profit_per_kwh: 0.03,
          battery_degradation_cost_per_kwh: 0.01,
          solar_drift_threshold_pct: 25.0,
          price_drift_threshold_pct: 20.0,
          load_drift_threshold_pct: 30.0,
          mqtt_enabled: false,
          mqtt_broker_host: 'localhost',
          mqtt_broker_port: 1883,
          mqtt_topic_prefix: 'fluxem',
          ha_url: 'http://homeassistant.local:8123',
          ha_token: '',
          ha_timezone: 'auto',
          ha_entity_mappings: {
            solar_forecast_entity: 'sensor.solcast_pv_forecast',
            buy_price_forecast_entity: 'sensor.amber_general_forecast',
            sell_price_forecast_entity: 'sensor.amber_feed_in_forecast',
            house_power_entity: 'sensor.power_meter_house',
            battery_soc_entity: 'sensor.battery_state_of_charge'
          }
        },
        battery: {
          capacity_kwh: 13.5,
          soc_percent: 50.0,
          min_soc_percent: 10.0,
          max_soc_percent: 100.0,
          max_charge_power_w: 5000.0,
          max_discharge_power_w: 5000.0,
          round_trip_efficiency: 0.90
        },
        chart: null,

        async init() {
          await this.loadConfig();
          await this.loadHaEntities();
        },

        switchTab(tab) {
          this.activeTab = tab;
          if (tab === 'preview') {
            this.$nextTick(() => {
              if (this.latestSchedule) {
                this.renderScheduleChart(this.latestSchedule);
              }
            });
          }
        },

        async loadConfig() {
          try {
            const res = await fetch('/api/v1/ui/config');
            if (res.ok) {
              const data = await res.json();
              this.config = Object.assign(this.config, data);
              if (data.battery) this.battery = Object.assign(this.battery, data.battery);
            }
          } catch (e) {
            console.error('Error loading config:', e);
          }
        },

        async loadHaEntities(notify = false) {
          this.loadingEntities = true;
          try {
            const res = await fetch('/api/v1/ha/entities', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ha_url: this.config.ha_url, ha_token: this.config.ha_token })
            });
            if (res.ok) {
              const data = await res.json();
              this.haEntities = data;
              this.haSensors = data.filter(e => e.domain === 'sensor' || e.domain === 'input_number' || e.domain === 'binary_sensor');
              this.haSwitches = data.filter(e => e.domain === 'switch' || e.domain === 'input_boolean' || e.domain === 'climate' || e.domain === 'water_heater' || e.domain === 'fan');

              // Smart categorization from backend tags
              this.haSolarSensors = data.filter(e => (e.categories && e.categories.includes('solar')) || (!e.categories && (e.entity_id.includes('solcast') || e.entity_id.includes('solar') || e.entity_id.includes('pv'))));
              this.haBuyPriceSensors = data.filter(e => (e.categories && e.categories.includes('buy_price')) || (!e.categories && (e.entity_id.includes('price') || e.entity_id.includes('tariff'))));
              this.haSellPriceSensors = data.filter(e => (e.categories && e.categories.includes('sell_price')) || (!e.categories && (e.entity_id.includes('feed_in') || e.entity_id.includes('export'))));
              this.haPowerSensors = data.filter(e => (e.categories && e.categories.includes('power')) || (!e.categories && (e.domain === 'sensor' && (e.unit === 'W' || e.unit === 'kW' || e.entity_id.includes('power')))));
              this.haBatterySensors = data.filter(e => (e.categories && e.categories.includes('battery')) || (!e.categories && (e.entity_id.includes('battery') || e.entity_id.includes('soc'))));

              if (notify) {
                if (data.length > 0) {
                  this.showToast(`Loaded ${data.length} entities from Home Assistant!`, 'success');
                } else {
                  this.showToast('Connected, but found 0 matching sensor/switch entities.', 'error');
                }
              }
            } else {
              if (notify) {
                this.showToast('Could not load entities from Home Assistant.', 'error');
              }
            }
          } catch (e) {
            console.error('Error fetching entities:', e);
            if (notify) {
              this.showToast('Error loading entities: ' + e.message, 'error');
            }
          } finally {
            this.loadingEntities = false;
          }
        },

        async saveConfig() {
          this.saving = true;
          try {
            const cleanConfig = JSON.parse(JSON.stringify(this.config));
            const cleanBattery = JSON.parse(JSON.stringify(this.battery));
            const payload = Object.assign({}, cleanConfig, { battery: cleanBattery });
            const res = await fetch('/api/v1/ui/config', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            });

            if (res.ok) {
              this.showToast('Configuration saved successfully!', 'success');
            } else {
              const err = await res.json();
              this.showToast(err.detail || 'Error saving configuration', 'error');
            }
          } catch (e) {
            this.showToast('Network error while saving', 'error');
          } finally {
            this.saving = false;
          }
        },

        async testHaConnection() {
          this.testingHa = true;
          this.lastSyncError = null;
          try {
            const res = await fetch('/api/v1/ha/test-connection', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ha_url: this.config.ha_url, ha_token: this.config.ha_token })
            });
            const data = await res.json();
            if (data.connected) {
              if (data.time_zone) {
                this.detectedTimezone = data.time_zone;
              }
              this.showToast('Connected to Home Assistant ' + (data.ha_version || '') + ' (' + (data.time_zone || '') + ')', 'success');
              await this.saveConfig();
              await this.loadHaEntities(true);
            } else {
              this.lastSyncError = data.message || 'Connection failed';
              this.showToast(this.lastSyncError, 'error');
            }
          } catch (e) {
            this.lastSyncError = 'Error testing connection: ' + e.message;
            this.showToast(this.lastSyncError, 'error');
          } finally {
            this.testingHa = false;
          }
        },

        async testMqttConnection() {
          this.testingMqtt = true;
          this.mqttStatusMessage = '';
          try {
            const res = await fetch('/api/v1/mqtt/test-connection', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                mqtt_broker_host: this.config.mqtt_broker_host,
                mqtt_broker_port: this.config.mqtt_broker_port,
                mqtt_username: this.config.mqtt_username,
                mqtt_password: this.config.mqtt_password
              })
            });
            const data = await res.json();
            this.mqttConnected = data.connected;
            this.mqttStatusMessage = data.message;
            if (data.connected) {
              this.showToast(data.message, 'success');
            } else {
              this.showToast(data.message || 'MQTT Connection failed', 'error');
            }
          } catch (e) {
            this.mqttConnected = false;
            this.mqttStatusMessage = 'Error: ' + e.message;
            this.showToast('Error testing MQTT connection: ' + e.message, 'error');
          } finally {
            this.testingMqtt = false;
          }
        },

        async syncAndOptimize() {
          this.syncingHa = true;
          this.lastSyncError = null;
          let scheduleData = null;

          try {
            await this.saveConfig();
            const res = await fetch('/api/v1/ha/sync-and-optimize', { method: 'POST' });
            if (!res.ok) {
              const err = await res.json();
              this.lastSyncError = err.detail || 'Sync failed';
              this.showToast(this.lastSyncError, 'error');
              return;
            }
            scheduleData = await res.json();
          } catch (e) {
            this.lastSyncError = 'Network error during Home Assistant sync: ' + e.message;
            this.showToast(this.lastSyncError, 'error');
            return;
          } finally {
            this.syncingHa = false;
          }

          if (scheduleData) {
            this.latestSchedule = scheduleData;
            this.activeTab = 'preview';
            this.showToast('Pulled sensors from HA & optimized successfully!', 'success');
            this.$nextTick(() => {
              this.renderScheduleChart(scheduleData);
            });
          }
        },

        addLoad() {
          this.config.deferrable_loads.push({
            id: 'load_' + (this.config.deferrable_loads.length + 1),
            name: 'New Appliance',
            nominal_power_w: 2400.0,
            required_hours: 3.0,
            continuous: true,
            critical: true,
            max_skip_days: 1,
            consecutive_days_skipped: 0,
            max_buy_price: null,
            solar_only: false,
            complete_on_cutoff: false,
            is_running: false,
            is_included_in_total_load: true,
            power_sensor_entity_id: '',
            switch_entity_id: ''
          });
        },

        removeLoad(index) {
          this.config.deferrable_loads.splice(index, 1);
        },

        showToast(msg, type = 'success') {
          this.toast = { show: true, message: msg, type };
          setTimeout(() => { this.toast.show = false; }, type === 'error' ? 8000 : 4000);
        },

        renderScheduleChart(data) {
          try {
            const ctx = document.getElementById('scheduleChart');
            if (!ctx) return;

            if (this.chart) {
              this.chart.destroy();
              this.chart = null;
            }

            const timestamps = data.timestamps || [];
            const labels = timestamps.map(t => {
              try {
                const d = new Date(t);
                if (!isNaN(d.getTime())) {
                  if (timestamps.length > 48) {
                    return d.toLocaleDateString([], { weekday: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                  }
                  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                }
              } catch (e) {}
              return typeof t === 'string' && t.length >= 16 ? t.substring(11, 16) : t;
            });

            const datasets = [
              {
                label: 'Solar Forecast (W)',
                data: data.solar_forecast_w || [],
                borderColor: '#f59e0b',
                backgroundColor: 'rgba(245, 158, 11, 0.12)',
                fill: true,
                tension: 0.3,
                pointRadius: 1
              },
              {
                label: 'Baseline Load (W)',
                data: data.baseline_load_w || [],
                borderColor: '#60a5fa',
                tension: 0.3,
                pointRadius: 1
              }
            ];

            if (data.battery_power_w && data.battery_power_w.length > 0) {
              datasets.push({
                label: 'Battery Power (W) [+Chg/-Dchg]',
                data: data.battery_power_w,
                borderColor: '#a855f7',
                borderDash: [3, 3],
                tension: 0.2,
                pointRadius: 1
              });
            }

            const defKeys = Object.keys(data.deferrable_load_power_w || {});
            defKeys.forEach((key, idx) => {
              const colors = ['#06b6d4', '#ec4899', '#8b5cf6', '#f43f5e'];
              datasets.push({
                label: 'Load: ' + key + ' (W)',
                data: data.deferrable_load_power_w[key],
                borderColor: colors[idx % colors.length],
                borderDash: [5, 5],
                tension: 0.1,
                pointRadius: 1
              });
            });

            if (data.battery_soc_percent && data.battery_soc_percent.length > 0) {
              datasets.push({
                label: 'Expected Battery SOC (%)',
                data: data.battery_soc_percent,
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.05)',
                yAxisID: 'y1',
                tension: 0.2,
                pointRadius: 1.5,
                borderWidth: 2.5
              });
            }

            this.chart = new Chart(ctx, {
              type: 'line',
              data: { labels, datasets },
              options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                  legend: {
                    display: true,
                    labels: { color: '#cbd5e1', font: { size: 11 } }
                  }
                },
                scales: {
                  x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8', maxRotation: 0, autoSkip: true, maxTicksLimit: 14 }
                  },
                  y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: { display: true, text: 'Power (Watts)', color: '#94a3b8' },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8' }
                  },
                  y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    min: 0,
                    max: 100,
                    title: { display: true, text: 'Battery SOC (%)', color: '#10b981' },
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#10b981', callback: val => val + '%' }
                  }
                }
              }
            });
          } catch (err) {
            console.error('Error rendering chart:', err);
          }
        },

        formatTimeLabel(t) {
          try {
            const d = new Date(t);
            if (!isNaN(d.getTime())) {
              return d.toLocaleDateString([], { weekday: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            }
          } catch (e) {}
          return typeof t === 'string' && t.length >= 16 ? t.substring(11, 16) : t;
        },

        getStepDeferrablePower(idx) {
          if (!this.latestSchedule || !this.latestSchedule.deferrable_load_power_w) return 0;
          let total = 0;
          for (const key of Object.keys(this.latestSchedule.deferrable_load_power_w)) {
            const arr = this.latestSchedule.deferrable_load_power_w[key];
            if (arr && arr[idx]) total += arr[idx];
          }
          return Math.round(total);
        },

        async runSimulation() {
          this.simulating = true;
          this.lastSyncError = null;
          let simData = null;

          try {
            const res = await fetch('/api/v1/ui/simulate', { method: 'POST' });
            if (!res.ok) {
              const err = await res.json();
              this.lastSyncError = err.detail || 'Simulation failed';
              this.showToast(this.lastSyncError, 'error');
              return;
            }
            simData = await res.json();
          } catch (e) {
            this.lastSyncError = 'Simulation error: ' + e.message;
            this.showToast(this.lastSyncError, 'error');
            return;
          } finally {
            this.simulating = false;
          }

          if (simData) {
            this.latestSchedule = simData;
            this.showToast('Simulation complete!', 'success');
            this.$nextTick(() => {
              this.renderScheduleChart(simData);
            });
          }
        }
      }
    }
  </script>
</body>
</html>
"""


def render_ui_html() -> HTMLResponse:
    """Returns the standalone WebUI dashboard HTML with current version."""
    content = HTML_TEMPLATE.replace("__FLUXEM_VERSION__", f"v{__version__}")
    return HTMLResponse(content=content, status_code=200)

