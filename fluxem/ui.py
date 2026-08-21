"""
FluxEM WebUI Dashboard and Configuration Interface v2.0.
Modern, responsive glassmorphism UI rendered directly by FastAPI using TailwindCSS and Alpine.js.
Features:
- Dedicated Home Dashboard with 24h midnight-to-midnight operational schedule.
- Plan of Record (Baseline) vs Realized Actuals tracking and Drift Telemetry.
- Horizon Toggle: Today (24h) vs Full Forecast (48h/72h).
- Collapsible, categorized Configuration Drawer/Modal for zero-clutter setup.
"""

from fastapi.responses import HTMLResponse
from fluxem import __version__

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FluxEM ⚡ Energy Optimization Dashboard</title>
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
    body { background-color: #090d16; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; }
    .glass { background: rgba(18, 26, 43, 0.75); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.07); }
    .glass-card { background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .glass-modal { background: rgba(11, 17, 32, 0.95); backdrop-filter: blur(24px); border: 1px solid rgba(255, 255, 255, 0.12); }
    [x-cloak] { display: none !important; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0b1120; }
    ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #334155; }
  </style>
</head>
<body class="min-h-screen flex flex-col antialiased selection:bg-emerald-500 selection:text-white" x-data="fluxemApp()" x-init="init()">

  <!-- Top Navbar -->
  <header class="border-b border-slate-800/80 bg-slate-950/90 sticky top-0 z-40 backdrop-blur-md">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <!-- Left: Logo & Status Pills -->
      <div class="flex items-center space-x-4">
        <div class="flex items-center space-x-3 cursor-pointer" @click="configModalOpen = false">
          <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-900/40">
            <i class="fa-solid fa-bolt text-slate-950 text-lg"></i>
          </div>
          <div>
            <h1 class="text-xl font-bold tracking-tight text-white flex items-center gap-2">
              FluxEM <span class="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono font-normal">__FLUXEM_VERSION__</span>
            </h1>
            <p class="text-[11px] text-slate-400 leading-none">Home Energy Optimization Engine</p>
          </div>
        </div>

        <!-- Live Status Pills -->
        <div class="hidden md:flex items-center space-x-2 pl-3 border-l border-slate-800 text-xs">
          <div class="px-2.5 py-1 rounded-full bg-slate-900 border flex items-center gap-1.5"
               :class="config.ha_url && config.ha_token ? 'border-emerald-500/30 text-emerald-300' : 'border-amber-500/30 text-amber-300'">
            <span class="w-1.5 h-1.5 rounded-full" :class="config.ha_url && config.ha_token ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'"></span>
            <span x-text="config.ha_url && config.ha_token ? 'HA Connected' : 'HA Offline'"></span>
          </div>

          <template x-if="config.mqtt_enabled">
            <div class="px-2.5 py-1 rounded-full bg-slate-900 border border-teal-500/30 text-teal-300 flex items-center gap-1.5">
              <span class="w-1.5 h-1.5 rounded-full bg-teal-400"></span>
              <span>MQTT Stream</span>
            </div>
          </template>

          <div class="px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 text-slate-400 font-mono" x-text="dashboard.timezone || 'UTC'"></div>
        </div>
      </div>

      <!-- Right: Primary Actions & Settings Trigger -->
      <div class="flex items-center space-x-3">
        <!-- Quick Sync & Optimize -->
        <button @click="syncAndOptimize()" :disabled="syncingHa" class="inline-flex items-center px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition shadow-lg shadow-emerald-900/30 disabled:opacity-50">
          <i class="fa-solid fa-arrows-rotate mr-1.5" :class="syncingHa ? 'animate-spin' : ''"></i>
          <span x-text="syncingHa ? 'Optimizing...' : 'Sync & Optimize'"></span>
        </button>

        <!-- Configuration Menu Button -->
        <button @click="openConfigModal()" class="inline-flex items-center px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition gap-1.5">
          <i class="fa-solid fa-sliders text-emerald-400"></i>
          <span>Configuration</span>
        </button>

        <a href="/docs" target="_blank" class="hidden lg:inline-flex items-center px-2.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 text-xs font-medium border border-slate-800 transition">
          <i class="fa-solid fa-book-open mr-1"></i> Docs
        </a>
      </div>
    </div>
  </header>

  <!-- Toast Notification -->
  <div x-show="toast.show" x-transition class="fixed bottom-5 right-5 z-50 max-w-md p-4 rounded-xl shadow-2xl border flex items-center space-x-3"
       :class="toast.type === 'success' ? 'bg-emerald-950/95 border-emerald-500/50 text-emerald-200' : 'bg-rose-950/95 border-rose-500/50 text-rose-200'">
    <i :class="toast.type === 'success' ? 'fa-solid fa-circle-check text-emerald-400' : 'fa-solid fa-circle-exclamation text-rose-400'" class="text-xl"></i>
    <div class="text-sm font-medium" x-text="toast.message"></div>
  </div>

  <!-- MAIN OPERATIONAL DASHBOARD (HOME SCREEN) -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6 flex-1 w-full">

    <!-- Sync Error Notice (if any) -->
    <div x-show="lastSyncError" x-transition class="bg-rose-950/80 border border-rose-500/50 rounded-xl p-4 flex items-start justify-between text-rose-200 text-sm">
      <div class="flex items-start space-x-3">
        <i class="fa-solid fa-triangle-exclamation text-rose-400 text-lg mt-0.5"></i>
        <div>
          <div class="font-semibold text-white">System Notice</div>
          <div class="text-xs text-rose-300 font-mono mt-1 whitespace-pre-wrap" x-text="lastSyncError"></div>
        </div>
      </div>
      <button @click="lastSyncError = null" class="text-rose-400 hover:text-white p-1 transition">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <!-- ROW 1: REAL-TIME ADHERENCE & DRIFT KPI CARDS -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      
      <!-- Card 1: Solar Adherence -->
      <div class="glass-card p-4 rounded-xl relative overflow-hidden">
        <div class="flex items-center justify-between text-xs text-slate-400">
          <span class="font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
            <i class="fa-solid fa-sun"></i> Solar Performance
          </span>
          <template x-if="dashboard.adherence.has_baseline_plan">
            <span class="px-2 py-0.5 rounded-full text-[11px] font-mono font-medium"
                  :class="dashboard.adherence.solar_drift_pct >= -10 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : (dashboard.adherence.solar_drift_pct >= -25 ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20')"
                  x-text="(dashboard.adherence.solar_drift_pct > 0 ? '+' : '') + dashboard.adherence.solar_drift_pct + '%'">
            </span>
          </template>
        </div>
        <div class="mt-2.5 flex items-baseline justify-between">
          <div>
            <div class="text-2xl font-bold text-white font-mono" x-text="dashboard.adherence.actual_solar_kwh + ' kWh'"></div>
            <div class="text-xs text-slate-400 mt-0.5">
              Actual vs <span class="text-slate-300 font-mono" x-text="dashboard.adherence.planned_solar_kwh + ' kWh'"></span> planned
            </div>
          </div>
          <div class="text-right text-[11px] text-slate-500 font-mono">
            <div>24h Target</div>
            <div class="text-slate-300 font-bold" x-text="dashboard.adherence.full_day_planned_solar_kwh + ' kWh'"></div>
          </div>
        </div>
      </div>

      <!-- Card 2: Household Consumption Adherence -->
      <div class="glass-card p-4 rounded-xl relative overflow-hidden">
        <div class="flex items-center justify-between text-xs text-slate-400">
          <span class="font-semibold uppercase tracking-wider text-sky-400 flex items-center gap-1.5">
            <i class="fa-solid fa-house"></i> Home Demand
          </span>
          <template x-if="dashboard.adherence.has_baseline_plan">
            <span class="px-2 py-0.5 rounded-full text-[11px] font-mono font-medium"
                  :class="Math.abs(dashboard.adherence.load_drift_pct) <= 15 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'"
                  x-text="(dashboard.adherence.load_drift_pct > 0 ? '+' : '') + dashboard.adherence.load_drift_pct + '%'">
            </span>
          </template>
        </div>
        <div class="mt-2.5 flex items-baseline justify-between">
          <div>
            <div class="text-2xl font-bold text-white font-mono" x-text="dashboard.adherence.actual_load_kwh + ' kWh'"></div>
            <div class="text-xs text-slate-400 mt-0.5">
              Actual vs <span class="text-slate-300 font-mono" x-text="dashboard.adherence.planned_load_kwh + ' kWh'"></span> planned
            </div>
          </div>
          <div class="text-right text-[11px] text-slate-500 font-mono">
            <div>24h Target</div>
            <div class="text-slate-300 font-bold" x-text="dashboard.adherence.full_day_planned_load_kwh + ' kWh'"></div>
          </div>
        </div>
      </div>

      <!-- Card 3: Battery State & Delta -->
      <div class="glass-card p-4 rounded-xl relative overflow-hidden">
        <div class="flex items-center justify-between text-xs text-slate-400">
          <span class="font-semibold uppercase tracking-wider text-emerald-400 flex items-center gap-1.5">
            <i class="fa-solid fa-car-battery"></i> Battery SOC
          </span>
          <template x-if="dashboard.adherence.battery_soc_delta !== null && dashboard.adherence.battery_soc_delta !== undefined">
            <span class="px-2 py-0.5 rounded-full text-[11px] font-mono font-medium"
                  :class="dashboard.adherence.battery_soc_delta >= 0 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : (dashboard.adherence.battery_soc_delta >= -10 ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20')"
                  x-text="(dashboard.adherence.battery_soc_delta > 0 ? '+' : '') + dashboard.adherence.battery_soc_delta + '% vs plan'">
            </span>
          </template>
        </div>
        <div class="mt-2.5 flex items-baseline justify-between">
          <div>
            <div class="text-2xl font-bold text-emerald-400 font-mono">
              <span x-text="(dashboard.adherence.actual_battery_soc !== null ? dashboard.adherence.actual_battery_soc : (battery.soc_percent || 50)).toFixed(1) + '%'"></span>
            </div>
            <div class="text-xs text-slate-400 mt-0.5">
              Target at now: <span class="text-slate-300 font-mono" x-text="(dashboard.adherence.planned_battery_soc !== null ? dashboard.adherence.planned_battery_soc.toFixed(1) : '--') + '%'"></span>
            </div>
          </div>
          <div class="text-right text-[11px] text-slate-500 font-mono">
            <div>Capacity</div>
            <div class="text-slate-300 font-bold" x-text="battery.capacity_kwh + ' kWh'"></div>
          </div>
        </div>
      </div>

      <!-- Card 4: Plan of Record & Watchdog -->
      <div class="glass-card p-4 rounded-xl relative overflow-hidden flex flex-col justify-between">
        <div class="flex items-center justify-between text-xs">
          <span class="font-semibold uppercase tracking-wider text-purple-400 flex items-center gap-1.5">
            <i class="fa-solid fa-shield-dog"></i> Plan of Record
          </span>
          <span class="px-2 py-0.5 rounded-full text-[11px] font-medium"
                :class="dashboard.adherence.is_baseline_locked ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'"
                x-text="dashboard.adherence.is_baseline_locked ? 'Locked' : 'Auto Baseline'">
          </span>
        </div>
        <div class="mt-2 flex items-center justify-between">
          <div class="text-xs text-slate-300">
            <div class="font-medium" x-text="dashboard.adherence.has_baseline_plan ? 'Active Today Baseline' : 'No Baseline Plan'"></div>
            <div class="text-[11px] text-slate-500 mt-0.5" x-text="dashboard.adherence.watchdog_status === 'holding_plan' ? 'Watchdog: Holding Plan' : 'Watchdog: Active MPC'"></div>
          </div>
          <div class="flex space-x-1.5">
            <button @click="lockBaseline()" title="Lock current plan as today's Plan of Record" class="px-2 py-1 bg-purple-950/60 hover:bg-purple-900/80 border border-purple-500/30 text-purple-300 rounded text-xs transition">
              <i class="fa-solid fa-lock"></i>
            </button>
            <button @click="resetBaseline()" title="Reset Baseline Plan" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-400 hover:text-slate-200 rounded text-xs transition">
              <i class="fa-solid fa-rotate-left"></i>
            </button>
          </div>
        </div>
      </div>

    </div>

    <!-- ROW 2: CHART CONTROLS & HORIZON TOGGLE -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
      <!-- Horizon Selector -->
      <div class="flex items-center space-x-2">
        <div class="bg-slate-900/90 p-1 rounded-xl border border-slate-800 flex items-center space-x-1 text-xs">
          <button @click="setScheduleView('today')" :class="scheduleView === 'today' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="px-3.5 py-1.5 rounded-lg border transition flex items-center gap-1.5">
            <i class="fa-regular fa-calendar-day"></i>
            <span>Today</span>
          </button>
          
          <template x-if="config.prediction_horizon_days > 1">
            <button @click="setScheduleView('full')" :class="scheduleView === 'full' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="px-3.5 py-1.5 rounded-lg border transition flex items-center gap-1.5">
              <i class="fa-solid fa-timeline"></i>
              <span x-text="'Full Forecast (' + config.prediction_horizon_days + ' Days)'"></span>
            </button>
          </template>
        </div>

        <span class="text-xs text-slate-500 font-mono hidden md:inline" x-text="'Local: ' + dashboard.today_date"></span>
      </div>

      <div class="text-slate-400 text-[11px] font-mono">
        Left: <span class="text-slate-200 font-semibold">Watts (W)</span> | Right: <span class="text-emerald-400 font-semibold">Battery SOC (%)</span>
      </div>
    </div>

    <!-- ROW 3: INTERACTIVE 24H POWER & BATTERY TRAJECTORY CHART -->
    <div class="glass p-6 rounded-2xl space-y-4">
      <div class="flex items-center justify-between text-xs text-slate-400 border-b border-slate-800/80 pb-3">
        <div class="flex items-center space-x-2">
          <i class="fa-solid fa-chart-line text-emerald-400"></i>
          <span class="font-medium text-slate-200">Power Dispatch, Battery Trajectory & Plan vs Reality</span>
        </div>
        <div class="text-[11px] text-slate-500">
          Click any legend item to toggle curve visibility
        </div>
      </div>
      
      <!-- 4-COLUMN GROUPED LEGEND -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 text-xs">
        
        <!-- Column 1: Solar -->
        <div class="space-y-2">
          <button @click="toggleGroup('solar')" :class="isGroupVisible('solar') ? 'text-amber-400 border-slate-800/80' : 'text-slate-600 line-through opacity-50 border-slate-800/40'" class="w-full font-semibold uppercase tracking-wider text-[10px] flex items-center justify-between gap-1.5 pb-1 border-b hover:text-amber-300 transition text-left cursor-pointer group">
            <span class="flex items-center gap-1.5"><i class="fa-solid fa-sun"></i> Solar</span>
            <i class="fa-solid text-[9px] opacity-60 group-hover:opacity-100" :class="isGroupVisible('solar') ? 'fa-eye' : 'fa-eye-slash'"></i>
          </button>
          <div class="flex flex-col gap-1.5 pt-0.5">
            <button @click="toggleDataset('solar_forecast')" :class="isDatasetVisible('solar_forecast') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-amber-300 transition text-left cursor-pointer">
              <span class="w-3.5 h-1.5 rounded-full bg-amber-400 shrink-0"></span>
              <span class="truncate">Forecast</span>
            </button>
            <button @click="toggleDataset('solar_actual')" :class="isDatasetVisible('solar_actual') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-amber-300 transition text-left cursor-pointer">
              <span class="w-2.5 h-2.5 rounded-full bg-amber-300 ring-2 ring-amber-500/40 shrink-0"></span>
              <span class="truncate">Actual</span>
            </button>
            <button @click="toggleDataset('solar_baseline')" :class="isDatasetVisible('solar_baseline') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-amber-300 transition text-left cursor-pointer">
              <span class="w-3.5 h-0.5 border-t-2 border-dashed border-amber-400/70 shrink-0"></span>
              <span class="truncate">Planned</span>
            </button>
          </div>
        </div>

        <!-- Column 2: Home Demand -->
        <div class="space-y-2">
          <button @click="toggleGroup('load')" :class="isGroupVisible('load') ? 'text-sky-400 border-slate-800/80' : 'text-slate-600 line-through opacity-50 border-slate-800/40'" class="w-full font-semibold uppercase tracking-wider text-[10px] flex items-center justify-between gap-1.5 pb-1 border-b hover:text-sky-300 transition text-left cursor-pointer group">
            <span class="flex items-center gap-1.5"><i class="fa-solid fa-house"></i> Home Demand</span>
            <i class="fa-solid text-[9px] opacity-60 group-hover:opacity-100" :class="isGroupVisible('load') ? 'fa-eye' : 'fa-eye-slash'"></i>
          </button>
          <div class="flex flex-col gap-1.5 pt-0.5">
            <button @click="toggleDataset('load_forecast')" :class="isDatasetVisible('load_forecast') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-sky-300 transition text-left cursor-pointer">
              <span class="w-3.5 h-1.5 rounded-full bg-sky-400 shrink-0"></span>
              <span class="truncate">Forecast</span>
            </button>
            <button @click="toggleDataset('load_actual')" :class="isDatasetVisible('load_actual') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-sky-300 transition text-left cursor-pointer">
              <span class="w-2.5 h-2.5 rounded-full bg-sky-300 ring-2 ring-sky-500/40 shrink-0"></span>
              <span class="truncate">Actual</span>
            </button>
            <button @click="toggleDataset('load_baseline')" :class="isDatasetVisible('load_baseline') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-sky-300 transition text-left cursor-pointer">
              <span class="w-3.5 h-0.5 border-t-2 border-dashed border-sky-400/70 shrink-0"></span>
              <span class="truncate">Planned</span>
            </button>
          </div>
        </div>

        <!-- Column 3: Battery -->
        <div class="space-y-2">
          <button @click="toggleGroup('battery')" :class="isGroupVisible('battery') ? 'text-emerald-400 border-slate-800/80' : 'text-slate-600 line-through opacity-50 border-slate-800/40'" class="w-full font-semibold uppercase tracking-wider text-[10px] flex items-center justify-between gap-1.5 pb-1 border-b hover:text-emerald-300 transition text-left cursor-pointer group">
            <span class="flex items-center gap-1.5"><i class="fa-solid fa-car-battery"></i> Battery</span>
            <i class="fa-solid text-[9px] opacity-60 group-hover:opacity-100" :class="isGroupVisible('battery') ? 'fa-eye' : 'fa-eye-slash'"></i>
          </button>
          <div class="flex flex-col gap-1.5 pt-0.5">
            <button @click="toggleDataset('battery_soc_projected')" :class="isDatasetVisible('battery_soc_projected') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-emerald-300 transition text-left cursor-pointer">
              <span class="w-3.5 h-1.5 rounded-full bg-emerald-400 shrink-0"></span>
              <span class="truncate">Projected SOC</span>
            </button>
            <button @click="toggleDataset('battery_soc_actual')" :class="isDatasetVisible('battery_soc_actual') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-emerald-300 transition text-left cursor-pointer">
              <span class="w-2.5 h-2.5 rounded-full bg-emerald-300 ring-2 ring-emerald-500/40 shrink-0"></span>
              <span class="truncate">Actual SOC</span>
            </button>
            <button @click="toggleDataset('battery_soc_baseline')" :class="isDatasetVisible('battery_soc_baseline') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-emerald-300 transition text-left cursor-pointer">
              <span class="w-3.5 h-0.5 border-t-2 border-dashed border-emerald-400/70 shrink-0"></span>
              <span class="truncate">Planned SOC</span>
            </button>
            <button @click="toggleDataset('battery_power')" :class="isDatasetVisible('battery_power') ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center gap-2 hover:text-purple-300 transition text-left cursor-pointer">
              <span class="w-3.5 h-0.5 border-t-2 border-dashed border-purple-400 shrink-0"></span>
              <span class="truncate">Power (+Chg/-Dchg)</span>
            </button>
          </div>
        </div>

        <!-- Column 4: Deferrable Loads -->
        <div class="space-y-2">
          <button @click="toggleGroup('loads')" :class="isGroupVisible('loads') ? 'text-cyan-400 border-slate-800/80' : 'text-slate-600 line-through opacity-50 border-slate-800/40'" class="w-full font-semibold uppercase tracking-wider text-[10px] flex items-center justify-between gap-1.5 pb-1 border-b hover:text-cyan-300 transition text-left cursor-pointer group">
            <span class="flex items-center gap-1.5"><i class="fa-solid fa-sliders"></i> Deferrable Loads</span>
            <i class="fa-solid text-[9px] opacity-60 group-hover:opacity-100" :class="isGroupVisible('loads') ? 'fa-eye' : 'fa-eye-slash'"></i>
          </button>
          <div class="flex flex-col gap-1.5 pt-0.5 max-h-28 overflow-y-auto pr-1">
            <template x-for="(load, lIdx) in (config.deferrable_loads || [])" :key="load.id">
              <button @click="toggleDataset('load_' + load.id)" :class="isDatasetVisible('load_' + load.id) ? 'text-slate-200' : 'text-slate-600 line-through opacity-50'" class="flex items-center justify-between gap-1 hover:text-cyan-300 transition text-left cursor-pointer">
                <div class="flex items-center gap-2 truncate">
                  <span class="w-3 h-0.5 border-t-2 border-dashed shrink-0" :style="'border-color: ' + getLoadColor(lIdx)"></span>
                  <span class="truncate" x-text="load.name || load.id"></span>
                </div>
                <span class="text-[10px] font-mono text-slate-500 shrink-0" x-text="(load.nominal_power_w / 1000).toFixed(1) + ' kW'"></span>
              </button>
            </template>
            <template x-if="!config.deferrable_loads || config.deferrable_loads.length === 0">
              <span class="text-slate-500 text-[11px] italic">No appliances configured</span>
            </template>
          </div>
        </div>

      </div>

      <div class="h-96 w-full relative" style="min-height: 384px;">
        <canvas id="scheduleChart"></canvas>
      </div>
    </div>

    <!-- ROW 4: DEFERRABLE APPLIANCES STATUS GRID -->
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white flex items-center gap-2">
          <i class="fa-solid fa-sliders text-emerald-400"></i> Deferrable Appliance Schedules & Live States
        </h3>
        <button @click="openConfigModal('loads')" class="text-xs text-emerald-400 hover:text-emerald-300 transition">
          Manage Appliances →
        </button>
      </div>

      <template x-if="config.deferrable_loads.length === 0">
        <div class="glass p-6 rounded-xl text-center text-slate-400 text-sm">
          No deferrable loads configured. <button @click="openConfigModal('loads')" class="text-emerald-400 underline">Add appliances</button> to automate pool pumps, hot water heaters, or EV charging.
        </div>
      </template>

      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" x-show="config.deferrable_loads.length > 0">
        <template x-for="(load, lIdx) in config.deferrable_loads" :key="load.id">
          <div class="glass p-4 rounded-xl border flex flex-col justify-between"
               :class="load.is_running ? 'border-emerald-500/40 bg-emerald-950/10' : 'border-slate-800'">
            <div class="flex items-start justify-between">
              <div>
                <div class="font-semibold text-white text-sm flex items-center gap-2">
                  <span x-text="load.name || load.id"></span>
                  <span class="text-[10px] px-2 py-0.5 rounded font-mono uppercase"
                        :class="load.critical ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-teal-500/10 text-teal-400 border border-teal-500/20'"
                        x-text="load.critical ? 'Critical' : 'Opportunistic'">
                  </span>
                </div>
                <div class="text-xs text-slate-400 mt-1">
                  Power: <span class="text-slate-200 font-mono" x-text="load.nominal_power_w + ' W'"></span> | Req: <span class="text-slate-200 font-mono" x-text="load.required_hours + 'h'"></span>
                </div>
              </div>
              <div>
                <span class="px-2 py-1 rounded text-xs font-mono font-bold"
                      :class="load.is_running ? 'bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/30' : 'bg-slate-800 text-slate-400'"
                      x-text="load.is_running ? 'ON (Running)' : 'OFF / Standby'">
                </span>
              </div>
            </div>

            <div class="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400 font-mono">
              <div>
                Mode: <span class="text-slate-300" x-text="load.continuous ? 'Continuous' : 'Flexible'"></span>
                <template x-if="load.solar_only">
                  <span class="ml-1 text-amber-400">☀️ Solar Only</span>
                </template>
              </div>
              <template x-if="load.power_sensor_entity_id || load.switch_entity_id">
                <div class="text-emerald-400 truncate max-w-[140px]" x-text="load.power_sensor_entity_id || load.switch_entity_id"></div>
              </template>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- ROW 5: INTERVAL DISPATCH & REALIZED TELEMETRY DATA TABLE -->
    <template x-if="activeScheduleData && activeScheduleData.timestamps">
      <div class="glass p-6 rounded-2xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800/80 pb-3">
          <div>
            <h3 class="font-semibold text-white text-sm flex items-center gap-2">
              <i class="fa-solid fa-table-list text-emerald-400"></i> Step-by-Step Power Routing & Telemetry Breakdown
            </h3>
            <p class="text-xs text-slate-400">Interval dispatch, battery energy trajectory, and realized sensor telemetry.</p>
          </div>
          <span class="text-xs px-2.5 py-1 rounded bg-slate-900 border border-slate-700 text-slate-300 font-mono" x-text="getTableTimestamps().length + ' intervals'"></span>
        </div>

        <div class="overflow-x-auto max-h-96 overflow-y-auto border border-slate-800/80 rounded-xl scroll-smooth" id="stepTableContainer">
          <table class="w-full text-left text-xs font-mono text-slate-300">
            <thead class="bg-slate-900/90 text-slate-400 uppercase tracking-wider sticky top-0 border-b border-slate-800 z-10">
              <tr>
                <th class="px-3.5 py-2.5">Time</th>
                <th class="px-3.5 py-2.5">Solar (Actual / Plan)</th>
                <th class="px-3.5 py-2.5">Load (Actual / Plan)</th>
                <th class="px-3.5 py-2.5">Def. Loads</th>
                <th class="px-3.5 py-2.5">Battery Power</th>
                <th class="px-3.5 py-2.5 text-center">SOC % (Actual / Plan)</th>
                <th class="px-3.5 py-2.5">Net Grid Flow</th>
                <th class="px-3.5 py-2.5">Buy Price</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60 bg-slate-950/40">
              <template x-for="(ts, idx) in getTableTimestamps()" :key="idx">
                <tr class="hover:bg-slate-800/40 transition"
                    :id="isCurrentTimestamp(ts) ? 'stepTableRowNow' : ''"
                    :class="isCurrentTimestamp(ts) ? 'bg-emerald-950/50 font-semibold ring-1 ring-emerald-500/40 text-emerald-200' : (isPastTimestamp(ts) ? 'opacity-80' : '')">
                  <!-- Time & Status Badge -->
                  <td class="px-3.5 py-2 whitespace-nowrap flex items-center gap-1.5">
                    <span x-text="formatTimeLabel(ts)"></span>
                    <template x-if="isCurrentTimestamp(ts)">
                      <span class="px-1.5 py-0.2 rounded text-[10px] bg-emerald-500 text-slate-950 font-bold uppercase shadow-sm shadow-emerald-500/50">NOW</span>
                    </template>
                    <template x-if="isPastTimestamp(ts) && !isCurrentTimestamp(ts)">
                      <span class="text-[10px] text-slate-500 font-sans">✓</span>
                    </template>
                  </td>

                  <!-- Solar Power (Actual vs Planned) -->
                  <td class="px-3.5 py-2 whitespace-nowrap text-amber-400">
                    <span x-text="getStepSolarDisplay(ts, idx)"></span>
                  </td>

                  <!-- Base Load (Actual vs Planned) -->
                  <td class="px-3.5 py-2 whitespace-nowrap text-sky-400">
                    <span x-text="getStepLoadDisplay(ts, idx)"></span>
                  </td>

                  <!-- Deferrable Loads Power -->
                  <td class="px-3.5 py-2 whitespace-nowrap text-pink-400" x-text="getStepDeferrablePower(idx) + ' W'"></td>

                  <!-- Battery Power -->
                  <td class="px-3.5 py-2 whitespace-nowrap">
                    <template x-if="activeScheduleData.battery_power_w && activeScheduleData.battery_power_w[idx] > 10">
                      <span class="text-emerald-400 font-semibold" x-text="'+' + Math.round(activeScheduleData.battery_power_w[idx]) + ' W (Chg)'"></span>
                    </template>
                    <template x-if="activeScheduleData.battery_power_w && activeScheduleData.battery_power_w[idx] < -10">
                      <span class="text-purple-400 font-semibold" x-text="Math.round(activeScheduleData.battery_power_w[idx]) + ' W (Dchg)'"></span>
                    </template>
                    <template x-if="!activeScheduleData.battery_power_w || Math.abs(activeScheduleData.battery_power_w[idx]) <= 10">
                      <span class="text-slate-600">0 W</span>
                    </template>
                  </td>

                  <!-- Battery SOC % (Actual vs Planned) -->
                  <td class="px-3.5 py-2 text-center whitespace-nowrap">
                    <span x-text="getStepSocDisplay(ts, idx)"></span>
                  </td>

                  <!-- Net Grid Flow -->
                  <td class="px-3.5 py-2 whitespace-nowrap">
                    <template x-if="activeScheduleData.grid_import_power_w && activeScheduleData.grid_import_power_w[idx] > 10">
                      <span class="text-rose-400 font-medium" x-text="'+' + Math.round(activeScheduleData.grid_import_power_w[idx]) + ' W (Import)'"></span>
                    </template>
                    <template x-if="activeScheduleData.grid_export_power_w && activeScheduleData.grid_export_power_w[idx] > 10">
                      <span class="text-emerald-400 font-medium" x-text="'-' + Math.round(activeScheduleData.grid_export_power_w[idx]) + ' W (Export)'"></span>
                    </template>
                    <template x-if="(!activeScheduleData.grid_import_power_w || activeScheduleData.grid_import_power_w[idx] <= 10) && (!activeScheduleData.grid_export_power_w || activeScheduleData.grid_export_power_w[idx] <= 10)">
                      <span class="text-slate-600">0 W</span>
                    </template>
                  </td>

                  <!-- Buy Price -->
                  <td class="px-3.5 py-2 text-slate-300" x-text="'$' + (activeScheduleData.buy_prices && activeScheduleData.buy_prices[idx] !== undefined ? activeScheduleData.buy_prices[idx].toFixed(3) : '0.000')"></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </template>

  </main>

  <!-- UNIFIED CONFIGURATION DRAWER / MODAL -->
  <div x-show="configModalOpen" x-transition.opacity class="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
    <div class="glass-modal w-full max-w-5xl max-h-[90vh] rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-slate-700/80" @click.away="configModalOpen = false">
      
      <!-- Modal Header -->
      <div class="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
        <div class="flex items-center space-x-3">
          <div class="w-8 h-8 rounded-lg bg-emerald-600/20 text-emerald-400 flex items-center justify-center border border-emerald-500/30">
            <i class="fa-solid fa-sliders"></i>
          </div>
          <div>
            <h2 class="text-lg font-bold text-white">FluxEM Configuration & Integrations</h2>
            <p class="text-xs text-slate-400">Configure Home Assistant sensors, deferrable loads, battery storage, and optimization thresholds.</p>
          </div>
        </div>

        <div class="flex items-center space-x-3">
          <button @click="saveConfig()" :disabled="saving" class="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition shadow-lg shadow-emerald-900/30 disabled:opacity-50 flex items-center gap-1.5">
            <i class="fa-solid fa-floppy-disk" :class="saving ? 'animate-spin fa-spinner' : ''"></i>
            <span x-text="saving ? 'Saving...' : 'Save Configuration'"></span>
          </button>
          <button @click="configModalOpen = false" class="text-slate-400 hover:text-white p-1.5 transition">
            <i class="fa-solid fa-xmark text-lg"></i>
          </button>
        </div>
      </div>

      <!-- Modal Body (Split: Sidebar Nav + Settings Panes) -->
      <div class="flex-1 flex overflow-hidden">
        
        <!-- Config Sidebar Navigation -->
        <div class="w-60 bg-slate-950/70 border-r border-slate-800/80 p-3 space-y-1 overflow-y-auto">
          <button @click="configTab = 'ha'" :class="configTab === 'ha' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium border transition flex items-center space-x-2.5">
            <i class="fa-solid fa-house-signal w-4 text-center"></i>
            <span>Home Assistant API</span>
          </button>

          <button @click="configTab = 'loads'" :class="configTab === 'loads' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium border transition flex items-center justify-between">
            <div class="flex items-center space-x-2.5">
              <i class="fa-solid fa-sliders w-4 text-center"></i>
              <span>Deferrable Loads</span>
            </div>
            <span class="px-1.5 py-0.5 rounded-full text-[10px] bg-slate-800 text-slate-300 font-mono" x-text="config.deferrable_loads.length"></span>
          </button>

          <button @click="configTab = 'battery'" :class="configTab === 'battery' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium border transition flex items-center space-x-2.5">
            <i class="fa-solid fa-car-battery w-4 text-center"></i>
            <span>Battery Storage</span>
          </button>

          <button @click="configTab = 'arbitrage'" :class="configTab === 'arbitrage' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium border transition flex items-center space-x-2.5">
            <i class="fa-solid fa-arrow-trend-up w-4 text-center"></i>
            <span>Grid Arbitrage & Tariffs</span>
          </button>

          <button @click="configTab = 'watchdog'" :class="configTab === 'watchdog' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium border transition flex items-center space-x-2.5">
            <i class="fa-solid fa-shield-dog w-4 text-center"></i>
            <span>Drift Watchdog</span>
          </button>

          <button @click="configTab = 'mqtt'" :class="configTab === 'mqtt' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-slate-200 border-transparent'" class="w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium border transition flex items-center space-x-2.5">
            <i class="fa-solid fa-network-wired w-4 text-center"></i>
            <span>MQTT Broker</span>
          </button>
        </div>

        <!-- Config Content Pane -->
        <div class="flex-1 p-6 overflow-y-auto bg-slate-900/30">
          
          <!-- SUBTAB 1: HOME ASSISTANT API -->
          <div x-show="configTab === 'ha'" class="space-y-6 max-w-3xl">
            <div>
              <h3 class="text-base font-semibold text-white">Direct Home Assistant API Connection</h3>
              <p class="text-xs text-slate-400 mt-0.5">Zero-YAML direct REST integration. Auto-discovers entities and historical sensors.</p>
            </div>

            <div class="glass p-5 rounded-xl space-y-4">
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Home Assistant URL</label>
                  <input type="text" x-model="config.ha_url" placeholder="http://192.168.1.100:8123" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Long-Lived Access Token</label>
                  <input type="password" x-model="config.ha_token" placeholder="eyJhbGciOi..." class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
              </div>

              <div class="flex items-center justify-between pt-2">
                <button @click="testHaConnection()" :disabled="testingHa" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition flex items-center gap-1.5">
                  <i class="fa-solid fa-plug" :class="testingHa ? 'animate-spin fa-spinner' : ''"></i>
                  <span>Test Connection & Fetch Entities</span>
                </button>
                <div class="text-xs text-slate-400 font-mono" x-text="detectedTimezone ? 'Timezone: ' + detectedTimezone : ''"></div>
              </div>
            </div>

            <!-- Planning Horizon & History Settings -->
            <div class="glass p-5 rounded-xl space-y-4">
              <h4 class="text-xs font-semibold uppercase tracking-wider text-slate-300">Horizon & Forecast Horizon</h4>
              <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Prediction Horizon</label>
                  <select x-model.number="config.prediction_horizon_days" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    <option :value="1">1 Day (24 Hours)</option>
                    <option :value="2">2 Days (48 Hours)</option>
                    <option :value="3">3 Days (72 Hours)</option>
                  </select>
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">History Lookback</label>
                  <select x-model.number="config.load_history_days" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    <option :value="1">Past 1 Day</option>
                    <option :value="3">Past 3 Days (Recommended)</option>
                    <option :value="7">Past 7 Days</option>
                    <option :value="14">Past 14 Days</option>
                  </select>
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Timezone Mode</label>
                  <input type="text" x-model="config.ha_timezone" placeholder="auto" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
              </div>
            </div>

            <!-- Entity Mappings -->
            <div class="glass p-5 rounded-xl space-y-4">
              <h4 class="text-xs font-semibold uppercase tracking-wider text-slate-300">Entity Mappings</h4>
              <div class="space-y-3 text-xs">
                <div>
                  <label class="block text-slate-300 mb-1">Solar PV Forecast Entity</label>
                  <input list="ha-solar-sensors" type="text" x-model="config.ha_entity_mappings.solar_forecast_entity" placeholder="sensor.solcast_pv_forecast" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1">Real-Time Solar Generation Entity (Live W)</label>
                  <input list="ha-solar-sensors" type="text" x-model="config.ha_entity_mappings.solar_power_entity" placeholder="sensor.solar_power" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1">Electricity Buy Price Forecast Entity</label>
                  <input list="ha-buy-price-sensors" type="text" x-model="config.ha_entity_mappings.buy_price_forecast_entity" placeholder="sensor.amber_general_forecast" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1">Electricity Feed-in / Export Forecast Entity</label>
                  <input list="ha-sell-price-sensors" type="text" x-model="config.ha_entity_mappings.sell_price_forecast_entity" placeholder="sensor.amber_feed_in_forecast" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1">Whole House Power Meter Entity</label>
                  <input list="ha-power-sensors" type="text" x-model="config.ha_entity_mappings.house_power_entity" placeholder="sensor.power_meter_house" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1">Battery State of Charge Entity</label>
                  <input list="ha-battery-sensors" type="text" x-model="config.ha_entity_mappings.battery_soc_entity" placeholder="sensor.battery_state_of_charge" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
              </div>
            </div>
          </div>

          <!-- SUBTAB 2: DEFERRABLE LOADS -->
          <div x-show="configTab === 'loads'" class="space-y-6 max-w-4xl">
            <div class="flex items-center justify-between">
              <div>
                <h3 class="text-base font-semibold text-white">Deferrable Loads Manager</h3>
                <p class="text-xs text-slate-400 mt-0.5">Configure thermal appliances, heat pumps, EV chargers, and pool pumps.</p>
              </div>
              <button @click="addLoad()" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition flex items-center gap-1.5">
                <i class="fa-solid fa-plus"></i> Add Appliance
              </button>
            </div>

            <div class="space-y-4">
              <template x-for="(load, idx) in config.deferrable_loads" :key="load.id">
                <div class="glass p-5 rounded-xl border border-slate-700/80 space-y-4">
                  <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <div class="flex items-center space-x-3">
                      <input type="text" x-model="load.name" placeholder="Appliance Name" class="bg-slate-900 border border-slate-700 rounded px-2.5 py-1 text-sm font-semibold text-white focus:border-emerald-500 focus:outline-none">
                      <input type="text" x-model="load.id" placeholder="id" class="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-xs text-slate-400 font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                    <button @click="removeLoad(idx)" class="text-rose-400 hover:text-rose-300 text-xs px-2 py-1 transition">
                      <i class="fa-solid fa-trash-can mr-1"></i> Remove
                    </button>
                  </div>

                  <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                    <div>
                      <label class="block text-slate-400 mb-1">Nominal Power (W)</label>
                      <input type="number" x-model.number="load.nominal_power_w" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                    <div>
                      <label class="block text-slate-400 mb-1">Required Hours (h)</label>
                      <input type="number" step="0.5" x-model.number="load.required_hours" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                    <div>
                      <label class="block text-slate-400 mb-1">Max Skip Days</label>
                      <input type="number" x-model.number="load.max_skip_days" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                    <div>
                      <label class="block text-slate-400 mb-1">Max Buy Price ($/kWh)</label>
                      <input type="number" step="0.01" x-model.number="load.max_buy_price" placeholder="No limit" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                  </div>

                  <!-- Toggles -->
                  <div class="flex flex-wrap gap-4 text-xs pt-1">
                    <label class="flex items-center space-x-2 cursor-pointer">
                      <input type="checkbox" x-model="load.critical" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0">
                      <span class="text-slate-300">Critical / Mandatory Daily Run</span>
                    </label>
                    <label class="flex items-center space-x-2 cursor-pointer">
                      <input type="checkbox" x-model="load.continuous" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0">
                      <span class="text-slate-300">Continuous (Unbroken Cycle)</span>
                    </label>
                    <label class="flex items-center space-x-2 cursor-pointer">
                      <input type="checkbox" x-model="load.solar_only" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0">
                      <span class="text-slate-300">Solar-Only Mode</span>
                    </label>
                    <label class="flex items-center space-x-2 cursor-pointer">
                      <input type="checkbox" x-model="load.complete_on_cutoff" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0">
                      <span class="text-slate-300">Thermostat Cutoff Detection</span>
                    </label>
                  </div>

                  <!-- Sensor & Switch IDs -->
                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs pt-1 border-t border-slate-800/60">
                    <div>
                      <label class="block text-slate-400 mb-1">Power Meter Entity (W)</label>
                      <input list="ha-power-sensors" type="text" x-model="load.power_sensor_entity_id" placeholder="sensor.pool_pump_power" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                    <div>
                      <label class="block text-slate-400 mb-1">Switch Entity ID</label>
                      <input list="ha-switches" type="text" x-model="load.switch_entity_id" placeholder="switch.pool_pump" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:border-emerald-500 focus:outline-none">
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- SUBTAB 3: BATTERY STORAGE -->
          <div x-show="configTab === 'battery'" class="space-y-6 max-w-3xl">
            <div>
              <h3 class="text-base font-semibold text-white">Battery Storage Parameters</h3>
              <p class="text-xs text-slate-400 mt-0.5">Usable capacity, operational state of charge limits, and power thresholds.</p>
            </div>

            <div class="glass p-5 rounded-xl space-y-4">
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Usable Capacity (kWh)</label>
                  <input type="number" step="0.1" x-model.number="battery.capacity_kwh" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Round-Trip Efficiency (0-1.0)</label>
                  <input type="number" step="0.01" min="0.5" max="1.0" x-model.number="battery.round_trip_efficiency" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Min SOC Limit (%)</label>
                  <input type="number" step="1" min="0" max="50" x-model.number="battery.min_soc_percent" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Max SOC Limit (%)</label>
                  <input type="number" step="1" min="50" max="100" x-model.number="battery.max_soc_percent" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Max Charge Power (W)</label>
                  <input type="number" step="100" x-model.number="battery.max_charge_power_w" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Max Discharge Power (W)</label>
                  <input type="number" step="100" x-model.number="battery.max_discharge_power_w" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
              </div>
            </div>
          </div>

          <!-- SUBTAB 4: GRID ARBITRAGE -->
          <div x-show="configTab === 'arbitrage'" class="space-y-6 max-w-3xl">
            <div>
              <h3 class="text-base font-semibold text-white">Dynamic Grid Arbitrage & Pre-Charging</h3>
              <p class="text-xs text-slate-400 mt-0.5">Automated wholesale grid pre-charging and feed-in tariff trading.</p>
            </div>

            <div class="glass p-5 rounded-xl space-y-4 text-xs">
              <label class="flex items-center space-x-3 cursor-pointer">
                <input type="checkbox" x-model="config.enable_export_arbitrage" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0 w-4 h-4">
                <div>
                  <div class="font-semibold text-white">Enable Feed-in Export Arbitrage</div>
                  <div class="text-slate-400">Allows battery discharge to grid during extreme feed-in price spikes if net profit exceeds wear cost.</div>
                </div>
              </label>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-3 border-t border-slate-800">
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Min Arbitrage Hurdle Profit ($/kWh)</label>
                  <input type="number" step="0.01" x-model.number="config.min_arbitrage_profit_per_kwh" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Battery Degradation Cost ($/kWh)</label>
                  <input type="number" step="0.005" x-model.number="config.battery_degradation_cost_per_kwh" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
              </div>
            </div>
          </div>

          <!-- SUBTAB 5: DRIFT WATCHDOG -->
          <div x-show="configTab === 'watchdog'" class="space-y-6 max-w-3xl">
            <div>
              <h3 class="text-base font-semibold text-white">Drift Watchdog Thresholds</h3>
              <p class="text-xs text-slate-400 mt-0.5">Prevents unnecessary re-runs by holding baseline plans until sensor variance crosses thresholds.</p>
            </div>

            <div class="glass p-5 rounded-xl space-y-4 text-xs">
              <div>
                <div class="flex justify-between text-slate-300 mb-1 font-medium">
                  <span>Solar Generation Drift Threshold</span>
                  <span class="font-mono text-emerald-400" x-text="config.solar_drift_threshold_pct + '%'"></span>
                </div>
                <input type="range" min="5" max="50" step="1" x-model.number="config.solar_drift_threshold_pct" class="w-full accent-emerald-500">
              </div>

              <div>
                <div class="flex justify-between text-slate-300 mb-1 font-medium">
                  <span>Buy Price Drift Threshold</span>
                  <span class="font-mono text-emerald-400" x-text="config.price_drift_threshold_pct + '%'"></span>
                </div>
                <input type="range" min="5" max="50" step="1" x-model.number="config.price_drift_threshold_pct" class="w-full accent-emerald-500">
              </div>

              <div>
                <div class="flex justify-between text-slate-300 mb-1 font-medium">
                  <span>Household Baseline Load Drift Threshold</span>
                  <span class="font-mono text-emerald-400" x-text="config.load_drift_threshold_pct + '%'"></span>
                </div>
                <input type="range" min="5" max="60" step="1" x-model.number="config.load_drift_threshold_pct" class="w-full accent-emerald-500">
              </div>
            </div>
          </div>

          <!-- SUBTAB 6: MQTT BROKER -->
          <div x-show="configTab === 'mqtt'" class="space-y-6 max-w-3xl">
            <div>
              <h3 class="text-base font-semibold text-white">MQTT Broker & Real-Time Controls</h3>
              <p class="text-xs text-slate-400 mt-0.5">Streams scheduled power curves and real-time switch commands directly to MQTT.</p>
            </div>

            <div class="glass p-5 rounded-xl space-y-4 text-xs">
              <label class="flex items-center space-x-3 cursor-pointer">
                <input type="checkbox" x-model="config.mqtt_enabled" class="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0 w-4 h-4">
                <span class="font-semibold text-white">Enable MQTT Publishing</span>
              </label>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-3 border-t border-slate-800">
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Broker Host</label>
                  <input type="text" x-model="config.mqtt_broker_host" placeholder="localhost" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Broker Port</label>
                  <input type="number" x-model.number="config.mqtt_broker_port" placeholder="1883" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Username (Optional)</label>
                  <input type="text" x-model="config.mqtt_username" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div>
                  <label class="block text-slate-300 mb-1 font-medium">Password (Optional)</label>
                  <input type="password" x-model="config.mqtt_password" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
                <div class="sm:col-span-2">
                  <label class="block text-slate-300 mb-1 font-medium">Topic Prefix</label>
                  <input type="text" x-model="config.mqtt_topic_prefix" placeholder="fluxem" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono focus:border-emerald-500 focus:outline-none">
                </div>
              </div>

              <div class="pt-2">
                <button @click="testMqttConnection()" :disabled="testingMqtt" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition flex items-center gap-1.5">
                  <i class="fa-solid fa-network-wired" :class="testingMqtt ? 'animate-spin fa-spinner' : ''"></i>
                  <span>Test MQTT Connection</span>
                </button>
              </div>
            </div>
          </div>

        </div>

      </div>

    </div>
  </div>

  <!-- Datalists for Auto-Complete with Smart Category Filtering -->
  <datalist id="ha-solar-sensors">
    <template x-for="e in haSolarSensors" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name"></option>
    </template>
  </datalist>

  <datalist id="ha-buy-price-sensors">
    <template x-for="e in haBuyPriceSensors" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name"></option>
    </template>
  </datalist>

  <datalist id="ha-sell-price-sensors">
    <template x-for="e in haSellPriceSensors" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name"></option>
    </template>
  </datalist>

  <datalist id="ha-power-sensors">
    <template x-for="e in haPowerSensors" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name"></option>
    </template>
  </datalist>

  <datalist id="ha-battery-sensors">
    <template x-for="e in haBatterySensors" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name"></option>
    </template>
  </datalist>

  <datalist id="ha-switches">
    <template x-for="e in haSwitches" :key="e.entity_id">
      <option :value="e.entity_id" :label="e.friendly_name"></option>
    </template>
  </datalist>

  <!-- Application Logic -->
  <script>
    function fluxemApp() {
      return {
        configModalOpen: false,
        configTab: 'ha',
        scheduleView: 'today', // 'today' or 'full'
        saving: false,
        simulating: false,
        testingHa: false,
        testingMqtt: false,
        syncingHa: false,
        lastSyncError: null,
        detectedTimezone: '',
        toast: { show: false, message: '', type: 'success' },
        datasetVisibility: {
          solar_forecast: true,
          solar_actual: true,
          solar_baseline: true,
          load_forecast: true,
          load_actual: true,
          load_baseline: true,
          battery_soc_projected: true,
          battery_soc_actual: true,
          battery_soc_baseline: true,
          battery_power: true,
        },
        
        dashboard: {
          timezone: 'UTC',
          current_time: new Date().toISOString(),
          today_date: new Date().toISOString().substring(0, 10),
          current_step_index: 0,
          horizon_days: 1,
          baseline_plan: null,
          active_schedule: null,
          actuals: {},
          adherence: {
            has_baseline_plan: false,
            is_baseline_locked: false,
            actual_solar_kwh: 0,
            planned_solar_kwh: 0,
            full_day_planned_solar_kwh: 0,
            solar_drift_pct: 0,
            actual_load_kwh: 0,
            planned_load_kwh: 0,
            full_day_planned_load_kwh: 0,
            load_drift_pct: 0,
            actual_battery_soc: null,
            planned_battery_soc: null,
            battery_soc_delta: null,
            watchdog_status: 'nominal'
          }
        },
        
        activeScheduleData: null,
        haEntities: [],
        haSolarSensors: [],
        haBuyPriceSensors: [],
        haSellPriceSensors: [],
        haPowerSensors: [],
        haBatterySensors: [],
        haSwitches: [],
        
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
            solar_power_entity: 'sensor.solar_power',
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
          await this.fetchDashboard();
          await this.loadHaEntities();
          this.$nextTick(() => {
            this.renderScheduleChart();
          });
          setTimeout(() => {
            this.renderScheduleChart();
          }, 150);
          setTimeout(() => {
            this.renderScheduleChart();
          }, 500);
          window.addEventListener('resize', () => {
            if (this.chart) this.chart.resize();
          });
        },

        openConfigModal(tab = 'ha') {
          this.configTab = tab;
          this.configModalOpen = true;
        },

        setScheduleView(view) {
          this.scheduleView = view;
          this.renderScheduleChart();
          this.scrollToNowRow();
        },

        isDatasetVisible(id) {
          return this.datasetVisibility[id] !== false;
        },

        toggleDataset(id) {
          if (this.datasetVisibility[id] === undefined) {
            this.datasetVisibility[id] = false;
          } else {
            this.datasetVisibility[id] = !this.datasetVisibility[id];
          }
          this.renderScheduleChart();
        },

        getGroupDatasetIds(group) {
          if (group === 'solar') return ['solar_forecast', 'solar_actual', 'solar_baseline'];
          if (group === 'load') return ['load_forecast', 'load_actual', 'load_baseline'];
          if (group === 'battery') return ['battery_soc_projected', 'battery_soc_actual', 'battery_soc_baseline', 'battery_power'];
          if (group === 'loads') return (this.config.deferrable_loads || []).map(l => 'load_' + l.id);
          return [];
        },

        isGroupVisible(group) {
          const ids = this.getGroupDatasetIds(group);
          if (ids.length === 0) return true;
          return ids.some(id => this.isDatasetVisible(id));
        },

        toggleGroup(group) {
          const ids = this.getGroupDatasetIds(group);
          const anyVisible = ids.some(id => this.isDatasetVisible(id));
          const targetState = !anyVisible;
          ids.forEach(id => {
            this.datasetVisibility[id] = targetState;
          });
          this.renderScheduleChart();
        },

        scrollToNowRow() {
          this.$nextTick(() => {
            setTimeout(() => {
              const container = document.getElementById('stepTableContainer');
              const nowRow = document.getElementById('stepTableRowNow');
              if (container && nowRow) {
                const rowTop = nowRow.offsetTop;
                const rowHeight = nowRow.offsetHeight;
                const containerHeight = container.clientHeight;
                container.scrollTo({
                  top: Math.max(0, rowTop - (containerHeight / 2) + (rowHeight / 2)),
                  behavior: 'smooth'
                });
              }
            }, 100);
          });
        },

        getLoadColor(idx) {
          const colors = ['#22d3ee', '#f43f5e', '#a855f7', '#fb923c', '#eab308', '#38bdf8'];
          return colors[idx % colors.length];
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

        async fetchDashboard() {
          try {
            const res = await fetch('/api/v1/ui/dashboard');
            if (res.ok) {
              const data = await res.json();
              this.dashboard = data;
              this.activeScheduleData = data.active_schedule || data.baseline_plan;
              this.$nextTick(() => {
                this.renderScheduleChart();
                this.scrollToNowRow();
              });
              setTimeout(() => {
                this.renderScheduleChart();
                this.scrollToNowRow();
              }, 120);
            }
          } catch (e) {
            console.error('Error loading dashboard data:', e);
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
              if (data.time_zone) this.detectedTimezone = data.time_zone;
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
            if (data.connected) {
              this.showToast(data.message, 'success');
            } else {
              this.showToast(data.message || 'MQTT Connection failed', 'error');
            }
          } catch (e) {
            this.showToast('Error testing MQTT connection: ' + e.message, 'error');
          } finally {
            this.testingMqtt = false;
          }
        },

        async loadHaEntities(notify = false) {
          try {
            const res = await fetch('/api/v1/ha/entities', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ha_url: this.config.ha_url, ha_token: this.config.ha_token })
            });
            if (res.ok) {
              const data = await res.json();
              this.haEntities = data;
              this.haSolarSensors = data.filter(e => (e.categories && e.categories.includes('solar')) || e.entity_id.includes('solcast') || e.entity_id.includes('solar') || e.entity_id.includes('pv'));
              this.haBuyPriceSensors = data.filter(e => (e.categories && e.categories.includes('buy_price')) || e.entity_id.includes('price') || e.entity_id.includes('tariff'));
              this.haSellPriceSensors = data.filter(e => (e.categories && e.categories.includes('sell_price')) || e.entity_id.includes('feed_in') || e.entity_id.includes('export'));
              this.haPowerSensors = data.filter(e => (e.categories && e.categories.includes('power')) || e.unit === 'W' || e.unit === 'kW' || e.entity_id.includes('power'));
              this.haBatterySensors = data.filter(e => (e.categories && e.categories.includes('battery')) || e.entity_id.includes('battery') || e.entity_id.includes('soc'));
              this.haSwitches = data.filter(e => e.domain === 'switch' || e.domain === 'input_boolean' || e.domain === 'climate' || e.domain === 'water_heater');
              if (notify) this.showToast(`Loaded ${data.length} entities from Home Assistant!`, 'success');
            }
          } catch (e) {
            console.error('Error fetching entities:', e);
          }
        },

        async syncAndOptimize() {
          this.syncingHa = true;
          this.lastSyncError = null;
          try {
            await this.saveConfig();
            const res = await fetch('/api/v1/ha/sync-and-optimize', { method: 'POST' });
            if (!res.ok) {
              const err = await res.json();
              this.lastSyncError = err.detail || 'Sync failed';
              this.showToast(this.lastSyncError, 'error');
              return;
            }
            const scheduleData = await res.json();
            this.activeScheduleData = scheduleData;
            await this.fetchDashboard();
            this.showToast('Pulled sensors from HA & optimized successfully!', 'success');
            this.$nextTick(() => {
              this.renderScheduleChart();
            });
          } catch (e) {
            this.lastSyncError = 'Sync error: ' + e.message;
            this.showToast(this.lastSyncError, 'error');
          } finally {
            this.syncingHa = false;
          }
        },

        async runSimulation() {
          this.simulating = true;
          this.lastSyncError = null;
          try {
            const res = await fetch('/api/v1/ui/simulate', { method: 'POST' });
            if (!res.ok) {
              const err = await res.json();
              this.lastSyncError = err.detail || 'Simulation failed';
              this.showToast(this.lastSyncError, 'error');
              return;
            }
            const simData = await res.json();
            this.activeScheduleData = simData;
            await this.fetchDashboard();
            this.showToast('24h Simulation with realistic plan & actuals generated!', 'success');
            this.$nextTick(() => {
              this.renderScheduleChart();
            });
          } catch (e) {
            this.lastSyncError = 'Simulation error: ' + e.message;
            this.showToast(this.lastSyncError, 'error');
          } finally {
            this.simulating = false;
          }
        },

        async lockBaseline() {
          try {
            const res = await fetch('/api/v1/baseline/lock', { method: 'POST' });
            if (res.ok) {
              this.showToast("Today's Baseline Plan of Record has been locked!", 'success');
              await this.fetchDashboard();
            }
          } catch (e) {
            this.showToast('Error locking baseline', 'error');
          }
        },

        async resetBaseline() {
          try {
            const res = await fetch('/api/v1/baseline/reset', { method: 'POST' });
            if (res.ok) {
              this.showToast('Baseline plan reset. Next optimization will establish new baseline.', 'success');
              await this.fetchDashboard();
            }
          } catch (e) {
            this.showToast('Error resetting baseline', 'error');
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

        // Helper calculations for table and chart
        getTableTimestamps() {
          const schedule = this.activeScheduleData || this.dashboard.active_schedule || this.dashboard.baseline_plan;
          if (!schedule || !schedule.timestamps) return [];
          if (this.scheduleView === 'today') {
            return schedule.timestamps.slice(0, 48);
          }
          return schedule.timestamps;
        },

        isPastTimestamp(ts) {
          try {
            const d = new Date(ts);
            return d.getTime() <= Date.now();
          } catch (e) { return false; }
        },

        isCurrentTimestamp(ts) {
          try {
            const d = new Date(ts).getTime();
            const now = Date.now();
            return now >= d && now < (d + 30 * 60 * 1000);
          } catch (e) { return false; }
        },

        getStepSolarDisplay(ts, idx) {
          const actual = this.dashboard.actuals && this.dashboard.actuals[ts];
          const plan = (this.activeScheduleData || this.dashboard.active_schedule || this.dashboard.baseline_plan)?.solar_forecast_w?.[idx] || 0;
          if (actual && actual.solar_power_w !== null && actual.solar_power_w !== undefined) {
            return Math.round(actual.solar_power_w) + ' W (act) / ' + Math.round(plan) + ' W (plan)';
          }
          return Math.round(plan) + ' W (plan)';
        },

        getStepLoadDisplay(ts, idx) {
          const actual = this.dashboard.actuals && this.dashboard.actuals[ts];
          const plan = (this.activeScheduleData || this.dashboard.active_schedule || this.dashboard.baseline_plan)?.baseline_load_w?.[idx] || 0;
          if (actual && (actual.baseline_load_w !== null || actual.house_power_w !== null)) {
            const actVal = actual.baseline_load_w !== null ? actual.baseline_load_w : actual.house_power_w;
            return Math.round(actVal) + ' W (act) / ' + Math.round(plan) + ' W (plan)';
          }
          return Math.round(plan) + ' W (plan)';
        },

        getStepSocDisplay(ts, idx) {
          const actual = this.dashboard.actuals && this.dashboard.actuals[ts];
          const plan = (this.activeScheduleData || this.dashboard.active_schedule || this.dashboard.baseline_plan)?.battery_soc_percent?.[idx];
          if (actual && actual.battery_soc_percent !== null && actual.battery_soc_percent !== undefined) {
            return actual.battery_soc_percent.toFixed(1) + '% (act) / ' + (plan !== undefined ? plan.toFixed(1) : '--') + '%';
          }
          return (plan !== undefined ? plan.toFixed(1) + '%' : '--');
        },

        getStepDeferrablePower(idx) {
          const schedule = this.activeScheduleData || this.dashboard.active_schedule || this.dashboard.baseline_plan;
          if (!schedule || !schedule.deferrable_load_power_w) return 0;
          let total = 0;
          for (const key of Object.keys(schedule.deferrable_load_power_w)) {
            const arr = schedule.deferrable_load_power_w[key];
            if (arr && arr[idx]) total += arr[idx];
          }
          return Math.round(total);
        },

        formatTimeLabel(t) {
          try {
            const d = new Date(t);
            if (!isNaN(d.getTime())) {
              return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            }
          } catch (e) {}
          return typeof t === 'string' && t.length >= 16 ? t.substring(11, 16) : t;
        },

        renderScheduleChart() {
          try {
            if (typeof Chart === 'undefined') {
              setTimeout(() => this.renderScheduleChart(), 100);
              return;
            }

            const ctx = document.getElementById('scheduleChart');
            if (!ctx) return;

            const schedule = this.activeScheduleData || this.dashboard.active_schedule || this.dashboard.baseline_plan;
            if (!schedule || !schedule.timestamps || schedule.timestamps.length === 0) return;
            this.activeScheduleData = schedule;

            // Safely destroy existing chart instance
            try {
              const existing = Chart.getChart(ctx);
              if (existing) existing.destroy();
            } catch (e) {}

            if (this.chart) {
              try { this.chart.destroy(); } catch (e) {}
              this.chart = null;
            }

            const allTimestamps = schedule.timestamps || [];
            const sliceCount = this.scheduleView === 'today' ? Math.min(48, allTimestamps.length) : allTimestamps.length;
            const timestamps = allTimestamps.slice(0, sliceCount);
            const curStepIdx = this.dashboard.current_step_index || 0;

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

            const datasets = [];
            const actuals = this.dashboard.actuals || {};
            const baseline = this.dashboard.baseline_plan || schedule;

            // 1. SOLAR GROUP
            // 1a. Solar Forecast (Solid Amber Area)
            datasets.push({
              id: 'solar_forecast',
              label: 'Solar Forecast (W)',
              data: (schedule.solar_forecast_w || []).slice(0, sliceCount),
              borderColor: '#f59e0b',
              backgroundColor: 'rgba(245, 158, 11, 0.12)',
              fill: true,
              hidden: !this.isDatasetVisible('solar_forecast'),
              tension: 0.3,
              pointRadius: 1,
              borderWidth: 2
            });

            // 1b. Actual Realized Solar
            const actualSolarData = timestamps.map((ts, idx) => {
              if (idx <= curStepIdx && actuals[ts] && actuals[ts].solar_power_w !== null && actuals[ts].solar_power_w !== undefined) {
                return actuals[ts].solar_power_w;
              }
              return null;
            });
            datasets.push({
              id: 'solar_actual',
              label: 'Actual Solar (W)',
              data: actualSolarData,
              borderColor: '#fbbf24',
              backgroundColor: 'rgba(251, 191, 36, 0.25)',
              hidden: !this.isDatasetVisible('solar_actual'),
              spanGaps: true,
              tension: 0.3,
              pointRadius: 3,
              borderWidth: 3
            });

            // 1c. Baseline Solar Plan of Record (Ghost Dashed Amber)
            if (baseline.solar_forecast_w) {
              datasets.push({
                id: 'solar_baseline',
                label: 'Baseline Solar Plan (W)',
                data: (baseline.solar_forecast_w || []).slice(0, sliceCount),
                borderColor: 'rgba(245, 158, 11, 0.45)',
                borderDash: [5, 5],
                hidden: !this.isDatasetVisible('solar_baseline'),
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5
              });
            }

            // 2. HOME DEMAND GROUP
            // 2a. Scheduled Baseline Load (Sky Blue)
            datasets.push({
              id: 'load_forecast',
              label: 'Home Load (W)',
              data: (schedule.baseline_load_w || []).slice(0, sliceCount),
              borderColor: '#38bdf8',
              hidden: !this.isDatasetVisible('load_forecast'),
              tension: 0.3,
              pointRadius: 1,
              borderWidth: 2
            });

            // 2b. Actual Realized Load
            const actualLoadData = timestamps.map((ts, idx) => {
              if (idx <= curStepIdx && actuals[ts]) {
                const act = actuals[ts];
                if (act.baseline_load_w !== null && act.baseline_load_w !== undefined) return act.baseline_load_w;
                if (act.house_power_w !== null && act.house_power_w !== undefined) return act.house_power_w;
              }
              return null;
            });
            datasets.push({
              id: 'load_actual',
              label: 'Actual Home Load (W)',
              data: actualLoadData,
              borderColor: '#0284c7',
              hidden: !this.isDatasetVisible('load_actual'),
              spanGaps: true,
              tension: 0.3,
              pointRadius: 3,
              borderWidth: 3
            });

            // 2c. Baseline Home Load Plan (Ghost Dashed Sky Blue)
            if (baseline.baseline_load_w) {
              datasets.push({
                id: 'load_baseline',
                label: 'Baseline Load Plan (W)',
                data: (baseline.baseline_load_w || []).slice(0, sliceCount),
                borderColor: 'rgba(56, 189, 248, 0.45)',
                borderDash: [5, 5],
                hidden: !this.isDatasetVisible('load_baseline'),
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5
              });
            }

            // 3. BATTERY GROUP
            // 3a. Battery Power Curve (Purple)
            if (schedule.battery_power_w && schedule.battery_power_w.length > 0) {
              datasets.push({
                id: 'battery_power',
                label: 'Battery Power (W) [+Chg/-Dchg]',
                data: (schedule.battery_power_w || []).slice(0, sliceCount),
                borderColor: '#c084fc',
                backgroundColor: 'rgba(192, 132, 252, 0.08)',
                fill: true,
                borderDash: [4, 3],
                hidden: !this.isDatasetVisible('battery_power'),
                tension: 0.2,
                pointRadius: 1,
                borderWidth: 2
              });
            }

            // 3b. Projected SOC (Green, Right Axis)
            if (schedule.battery_soc_percent && schedule.battery_soc_percent.length > 0) {
              datasets.push({
                id: 'battery_soc_projected',
                label: 'Projected Battery SOC (%)',
                data: (schedule.battery_soc_percent || []).slice(0, sliceCount),
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.08)',
                yAxisID: 'y1',
                hidden: !this.isDatasetVisible('battery_soc_projected'),
                tension: 0.2,
                pointRadius: 1.5,
                borderWidth: 2.5
              });
            }

            // 3c. Actual Battery SOC (Mint Green Points, Right Axis)
            const actualSocData = timestamps.map((ts, idx) => {
              if (idx <= curStepIdx && actuals[ts] && actuals[ts].battery_soc_percent !== null && actuals[ts].battery_soc_percent !== undefined) {
                return actuals[ts].battery_soc_percent;
              }
              return null;
            });
            datasets.push({
              id: 'battery_soc_actual',
              label: 'Actual Battery SOC (%)',
              data: actualSocData,
              borderColor: '#34d399',
              yAxisID: 'y1',
              hidden: !this.isDatasetVisible('battery_soc_actual'),
              spanGaps: true,
              tension: 0.2,
              pointRadius: 3.5,
              borderWidth: 3
            });

            // 3d. Baseline Planned SOC (Ghost Dashed Green, Right Axis)
            if (baseline.battery_soc_percent && baseline.battery_soc_percent.length > 0) {
              datasets.push({
                id: 'battery_soc_baseline',
                label: 'Baseline Planned SOC (%)',
                data: (baseline.battery_soc_percent || []).slice(0, sliceCount),
                borderColor: 'rgba(16, 185, 129, 0.5)',
                borderDash: [6, 6],
                yAxisID: 'y1',
                hidden: !this.isDatasetVisible('battery_soc_baseline'),
                tension: 0.2,
                pointRadius: 0,
                borderWidth: 1.5
              });
            }

            // 4. DEFERRABLE LOADS GROUP (Friendly Names & Clear Stepped Fill Blocks)
            const defKeys = Object.keys(schedule.deferrable_load_power_w || {});
            defKeys.forEach((key, idx) => {
              const loadDef = (this.config.deferrable_loads || []).find(l => l.id === key);
              const friendlyName = loadDef?.name || key;
              const loadColor = this.getLoadColor(idx);
              const loadData = (schedule.deferrable_load_power_w[key] || []).slice(0, sliceCount);
              datasets.push({
                id: 'load_' + key,
                label: friendlyName + ' (W)',
                data: loadData,
                borderColor: loadColor,
                backgroundColor: loadColor + '28',
                fill: true,
                stepped: 'before',
                hidden: !this.isDatasetVisible('load_' + key),
                tension: 0,
                pointRadius: 0,
                pointHoverRadius: 4,
                borderWidth: 2
              });
            });

            const nowLinePlugin = {
              id: 'nowLine',
              afterDraw: (chart) => {
                const curIdx = chart.config.options.plugins.nowLine?.stepIndex;
                if (curIdx === undefined || curIdx === null || curIdx < 0) return;
                
                let x = null;
                if (chart.scales && chart.scales.x) {
                  x = chart.scales.x.getPixelForValue(curIdx);
                }
                if (x === null || x === undefined || isNaN(x)) {
                  const meta = chart.getDatasetMeta(0);
                  if (meta && meta.data && meta.data[curIdx]) {
                    x = meta.data[curIdx].x;
                  }
                }
                if (x === null || x === undefined || isNaN(x)) return;
                
                const { top, bottom } = chart.chartArea;
                const ctx = chart.ctx;
                
                ctx.save();
                // Vertical glowing line
                ctx.beginPath();
                ctx.setLineDash([4, 4]);
                ctx.moveTo(x, top);
                ctx.lineTo(x, bottom);
                ctx.lineWidth = 2;
                ctx.strokeStyle = '#f43f5e';
                ctx.shadowColor = 'rgba(244, 63, 94, 0.5)';
                ctx.shadowBlur = 6;
                ctx.stroke();
                
                // NOW badge pill
                ctx.setLineDash([]);
                ctx.fillStyle = '#f43f5e';
                ctx.shadowBlur = 0;
                
                const badgeText = 'NOW';
                ctx.font = 'bold 10px monospace';
                const textWidth = ctx.measureText(badgeText).width;
                const badgeWidth = textWidth + 10;
                const badgeHeight = 16;
                const badgeX = Math.min(Math.max(x - badgeWidth / 2, chart.chartArea.left), chart.chartArea.right - badgeWidth);
                const badgeY = top - 2;
                
                ctx.beginPath();
                if (ctx.roundRect) {
                  ctx.roundRect(badgeX, badgeY, badgeWidth, badgeHeight, 4);
                } else {
                  ctx.rect(badgeX, badgeY, badgeWidth, badgeHeight);
                }
                ctx.fill();
                
                ctx.fillStyle = '#ffffff';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(badgeText, badgeX + badgeWidth / 2, badgeY + badgeHeight / 2);
                
                ctx.restore();
              }
            };

            this.chart = new Chart(ctx, {
              type: 'line',
              data: { labels, datasets },
              plugins: [nowLinePlugin],
              options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                  legend: {
                    display: false
                  },
                  nowLine: {
                    stepIndex: curStepIdx
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
                    grid: {
                      color: (ctx) => (ctx.tick && ctx.tick.value === 0 ? 'rgba(255, 255, 255, 0.25)' : 'rgba(255, 255, 255, 0.05)'),
                      lineWidth: (ctx) => (ctx.tick && ctx.tick.value === 0 ? 1.5 : 1)
                    },
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
