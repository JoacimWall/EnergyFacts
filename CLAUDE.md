# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom integration ("My Solar Cells") that tracks solar energy production economics using the Tibber API, calculates financial metrics, and projects ROI over 30 years. Includes a custom Lovelace card for ROI visualization. Domain: `my_solar_cells`.

The Python financial/ROI engines are ported from a .NET app — `financial_engine.py` from `HistoryDataService.cs`, `roi_engine.py` from `RoiService.cs`, `tibber_client.py` from `TibberService.cs`. Preserve calculation parity with the original .NET logic.

## Commands

### Python tests
```bash
pip install pytest pytest-asyncio aiohttp  # one-time setup
pytest tests/                               # run all tests
pytest tests/test_financial_engine.py       # run single test file
pytest tests/test_financial_engine.py::test_function_name -v  # run single test
```

Tests mock all Home Assistant modules in `conftest.py` (no full HA install needed).

### Lovelace card (TypeScript)
```bash
cd custom_cards/my-solar-cells-roi-card
npm install         # one-time setup
npm run build       # build with rollup → my-solar-cells-roi-card.js
npm run watch       # dev mode with file watching
```

The compiled JS is copied to `custom_components/my_solar_cells/my-solar-cells-roi-card.js` for HA to serve — never forget this.

### Panel (TypeScript)
```bash
cd custom_cards/my-solar-cells-panel
npm install         # one-time setup
npm run build       # build with rollup → my-solar-cells-panel.js
```

After building, always copy the built JS to the serving directory:
```bash
cp custom_cards/my-solar-cells-panel/my-solar-cells-panel.js custom_components/my_solar_cells/my-solar-cells-panel.js
```

### Version bump for cache-busting
After changing any JS file (panel or card), bump the version in `custom_components/my_solar_cells/manifest.json`. The `__init__.py` appends `?v={version}` to JS URLs so browsers fetch the new file instead of serving a cached copy.

## Architecture

### Data Flow
Tibber API → `tibber_client.py` → `database.py` (SQLite persistence) → `coordinator.py` (orchestration) → `financial_engine.py` + `roi_engine.py` (calculations) → `sensor.py` (HA entities)

The panel uses a separate path: `websocket_api.py` ↔ browser (WebSocket) for on-demand queries (hourly data, heat sources, yearly params, simulations).

### Key Modules (in `custom_components/my_solar_cells/`)
- **coordinator.py**: `DataUpdateCoordinator` subclass. Fetches spot prices every 15 min, consumption/production every 60 min. Performs historical import on first run. Enriches Tibber data with HA sensor values.
- **financial_engine.py**: Pure calculation module. `CalcParams` dataclass holds config. `calculate_period()` processes hourly records into period aggregates. `generate_monthly_report()` creates period summaries. `get_calc_params_for_year()` returns per-year financial params. Tax reduction is capped when yearly production sold > purchased.
- **roi_engine.py**: 30-year projection with panel degradation (default 0.25%/yr) and price development (default 5%/yr). Handles incomplete current year by extrapolating. Tax reduction set to end in 2026.
- **tibber_client.py**: Async GraphQL client using aiohttp. Queries: test connection, get homes, consumption/production (HOURLY), spot prices (QUARTER_HOURLY).
- **config_flow.py**: 5-step setup wizard — Tibber key → home selection → HA sensors → financial params → investment/ROI.
- **database.py**: SQLite persistence (replaced the old JSON `storage.py`). Tables: `hourly_energy`, `spot_prices`, `yearly_params`, `heat_sources`, `heat_source_energy`, `metadata`. Hourly records keyed by UTC timestamp. Runs blocking SQLite calls via `hass.async_add_executor_job`.
- **sensor.py**: 30+ sensors grouped by period (daily/monthly/yearly/lifetime/spot price). Uses `SensorEntity` with proper `device_class` and `state_class`.
- **websocket_api.py**: WebSocket commands for the panel frontend — fetches hourly data, heat source breakdowns, yearly params, and battery simulation results on demand.
- **simulation_engine.py**: Battery simulation — ported from `HistoryDataService.cs` lines 208–267. `simulate_battery_add()` runs all-or-nothing charge/discharge over hourly records.
- **heat_source_engine.py**: Splits heat source energy into components (compressor vs electric heater) based on power thresholds. Tracks per-hour cost using spot prices.
- **entity.py**: Base `MySolarCellsEntity(CoordinatorEntity)` — sets `unique_id`, `device_info`, and `has_entity_name`.

### Lovelace Card (`custom_cards/my-solar-cells-roi-card/`)
Built with Lit (web components) + TypeScript. Rollup bundles to single JS file. Displays ROI projection chart from the `roi_payback_year` sensor's attributes.

### Panel (`custom_cards/my-solar-cells-panel/`)
Full-page HA panel built with Lit + TypeScript. Multi-view layout: overview, hourly energy, ROI, heat sources, hourly heat, sensors, yearly params, and fakta. Communicates with the backend via WebSocket API (`websocket_api.py`). Localization via `localize.ts`.

## Swedish Financial Model

All monetary values are in SEK. Key parameters with defaults:
- Tax reduction (skattereduktion): 0.60 SEK/kWh
- Grid compensation (nätnytta): 0.078 SEK/kWh
- Transfer fee (överföringsavgift): 0.30 SEK/kWh
- Energy tax (energiskatt): 0.49 SEK/kWh

## Code Conventions

- `from __future__ import annotations` in all Python files
- Type hints throughout, dataclasses for config/data structures
- Module-level `_LOGGER = logging.getLogger(__name__)`
- Async/await with `_async_` prefix convention for async methods
- Constants in `const.py` as `UPPER_SNAKE_CASE`
- No linter config — follows Home Assistant style conventions
