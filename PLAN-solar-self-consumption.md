# Solar self-consumption flag for heat sources

## Context
Today the heat source feature (`custom_components/my_solar_cells/heat_source_engine.py` + the panel "Configuration" view) tracks any energy consumer with one cumulative kWh sensor and an optional `has_compressor` flag that splits energy between heat pump vs immersion heater. The user already added two separate entries — "Laddning bil Totalt" (`sensor.easee_lifetime_energy`) and "Ladning bil Solel" (`sensor.charge_car_sun_energy_total`) — to approximate solar self-consumption for the car charger, but both rows cost the energy at the *purchased* rate, which over-counts cost.

The user wants a new mode on a heat source: provide both a total energy sensor AND a solar energy sensor, then split each hour into `purchased_kwh = total − solar` (costed as today: `spot + transfer_fee + energy_tax`) and `solar_kwh` (valued exactly like sold solar: `unit_price_sold + grid_compensation + tax_reduction (capped yearly)`).

User-confirmed constraints:
- New flag `has_solar` is **mutually exclusive** with `has_compressor`. A solar-mode source has a single component (`electric_heater`).
- Solar valuation formula must match the existing sold-solar calc exactly — same numbers as `production_sold_profit` + `production_sold_grid_compensation_profit` + `production_sold_tax_reduction_profit` (financial_engine.py:256-266, with the yearly cap from financial_engine.py:490-502 applied at aggregation time, not per hour).

## Critical files

Backend (Python):
- `custom_components/my_solar_cells/database.py` — schema + heat_source CRUD
- `custom_components/my_solar_cells/heat_source_engine.py` — `HeatSourceConfig`, `load_heat_source_config`, `calculate_heat_source_period`
- `custom_components/my_solar_cells/coordinator.py` — `_process_heat_source` (lines 560-649), `_backfill_heat_source` (lines 651-784)
- `custom_components/my_solar_cells/websocket_api.py` — `ws_save_heat_source` (lines 682-722), `ws_get_heat_source_breakdown` (lines 614-679)

Frontend (TypeScript / Lit):
- `custom_cards/my-solar-cells-panel/src/views/heat-view.ts` — form rendering (lines 443-488), save handler (lines 231-266)
- `custom_cards/my-solar-cells-panel/src/types.ts` — heat source types
- `custom_cards/my-solar-cells-panel/src/localize.ts` — i18n strings (heat keys at lines 181-213, 420-452)

Reused (no edits):
- `financial_engine.py::get_calc_params_for_year` (line 212) for per-year overrides of `grid_compensation` / `tax_reduction`
- The yearly tax-reduction cap pattern (financial_engine.py:490-502) — applied at the aggregation layer

## Data model

### `heat_sources.config` (JSON, no schema change needed)
Add two keys:
```json
{
  "has_compressor": false,
  "has_solar": true,
  "solar_sensor": "sensor.charge_car_sun_energy_total",
  "components": [{"id": "electric_heater", "name": "Electricity use"}]
}
```

### `heat_source_energy` table — additive migration
Add two columns:
- `solar_energy_kwh REAL DEFAULT 0` — solar kWh for that hour bucket
- `solar_spot_value_sek REAL DEFAULT 0` — `solar_kwh × unit_price_sold` (spot-only, mirrors how `production_sold_profit` is stored hourly; grid_compensation + tax_reduction added at aggregation)

Migration (idempotent, runs after `executescript` in `_setup_sync`):
```python
def _migrate_sync(self) -> None:
    cols = {row[1] for row in self._conn.execute("PRAGMA table_info(heat_source_energy)").fetchall()}
    if "solar_energy_kwh" not in cols:
        self._conn.execute("ALTER TABLE heat_source_energy ADD COLUMN solar_energy_kwh REAL DEFAULT 0")
    if "solar_spot_value_sek" not in cols:
        self._conn.execute("ALTER TABLE heat_source_energy ADD COLUMN solar_spot_value_sek REAL DEFAULT 0")
    self._conn.commit()
```
Also update `_SCHEMA_SQL` so fresh installs include the columns from the start.

### `HeatSourceConfig` dataclass diff
```python
@dataclass
class HeatSourceConfig:
    id: str
    name: str
    energy_sensor: str
    power_sensor: str = ""
    has_compressor: bool = True
    has_solar: bool = False           # NEW
    solar_sensor: str = ""            # NEW
    components: list[dict] = field(default_factory=list)
    electric_heater_threshold_w: float = DEFAULT_ELPATRON_THRESHOLD_W
```
`load_heat_source_config`: read `has_solar` and `solar_sensor` from config JSON; if `has_solar=True`, defensively force `has_compressor=False` and use single-component shape (`[{id: "electric_heater", name: "Electricity use"}]`).

## Backend changes

### `database.py`
- Update `_SCHEMA_SQL` and add `_migrate_sync` (snippet above), called from `_setup_sync`.
- `upsert_heat_source_energy(...)`: add params `solar_energy_kwh: float = 0.0`, `solar_spot_value_sek: float = 0.0`. Persist on INSERT; sum on UPDATE (additive accumulation, same as `energy_kwh`/`cost_sek`).
- `get_heat_source_energy_summary`: add `COALESCE(SUM(solar_energy_kwh), 0)` and `COALESCE(SUM(solar_spot_value_sek), 0)` to result.
- New helper `get_unit_price_sold_for_hour(hour_iso) -> float | None` — `SELECT unit_price_sold FROM hourly_energy WHERE timestamp = ?` (mirror `get_average_price_for_hour`).

### `heat_source_engine.py`
- `HeatSourceConfig`: add `has_solar`, `solar_sensor` (above).
- `load_heat_source_config`: parse new fields; force mutual exclusion.
- `ComponentPeriodStats` and `HeatSourcePeriodStats`: add `solar_energy_kwh`, `solar_spot_value_sek`, `purchased_kwh`, `purchased_cost_sek`, `has_solar` (defaults preserve current behavior).
- `calculate_heat_source_period`: sum the new columns from rows; carry `has_solar` through from the parsed config.

### `coordinator.py::_process_heat_source` — extended pseudocode for has_solar branch
```
read current_energy from hs.energy_sensor → energy_delta (existing logic)
if energy_delta <= 0: return

solar_delta = 0.0
if hs.has_solar and hs.solar_sensor:
    read current_solar from hs.solar_sensor
    previous_solar = self._last_heat_readings.get(f"solar_{hs.id}")
    self._last_heat_readings[f"solar_{hs.id}"] = current_solar
    if previous_solar is not None and current_solar >= previous_solar:
        solar_delta = current_solar - previous_solar
    solar_delta = max(0.0, min(solar_delta, energy_delta))   # clamp

purchased_delta = energy_delta - solar_delta
implied_power_w = (energy_delta / elapsed_hours) * 1000      # unchanged

spot_price = storage.get_average_price_for_hour(hour_iso) or 0.0
year_params = get_calc_params_for_year(hour_iso[:4], self._calc_params, self._yearly_params)

if hs.has_solar:
    fixed_per_kwh = year_params.transfer_fee + year_params.energy_tax
    purchased_cost = purchased_delta * (spot_price + fixed_per_kwh)

    unit_price_sold = storage.get_unit_price_sold_for_hour(hour_iso)
    if unit_price_sold is None: unit_price_sold = spot_price   # fallback (live tick before Tibber backfill)
    solar_spot_value = solar_delta * unit_price_sold

    storage.upsert_heat_source_energy(
        timestamp=hour_iso, heat_source_id=hs.id, component="electric_heater",
        energy_kwh=purchased_delta, cost_sek=purchased_cost,
        avg_power_w=implied_power_w, spot_price=spot_price, samples=1,
        solar_energy_kwh=solar_delta, solar_spot_value_sek=solar_spot_value,
    )
else:
    # existing path unchanged: split_energy_by_power + per-component upsert
```

### `coordinator.py::_backfill_heat_source`
When `hs.has_solar and hs.solar_sensor`, do parallel `statistics_during_period` calls for `{hs.solar_sensor}` over the same 5-minute and hourly windows. Build `solar_hour_buckets` keyed by hour; in the per-hour loop apply the same has_solar logic above. Look up `unit_price_sold` per hour from `hourly_energy` (cache results to avoid repeated queries).

### `websocket_api.py`
- `ws_save_heat_source`: parse `config` JSON server-side; reject if both `has_compressor` and `has_solar` are true (`connection.send_error(msg["id"], "invalid_config", ...)`). The existing data wipe + backfill-flag clear (lines 715-717) already triggers a clean re-import on every save — no extra trigger logic needed.
- `ws_get_heat_source_breakdown`: extend per-source result with `has_solar`, `solar_energy_kwh`, `solar_value_sek`, `purchased_kwh`, `purchased_cost_sek`. Apply the yearly tax-reduction cap inside `_calc()` by grouping rows by year (`timestamp[:4]`), looking up `get_calc_params_for_year` per year, and applying `min(solar_kwh_year, purchased_kwh_year) * tax_reduction` — same shape as financial_engine.py:492-502.
  - Final solar value per year: `solar_spot_value_sek + (solar_kwh × grid_compensation) + capped_tax_reduction`.

## Frontend changes

### `heat-view.ts` — replace `_formHasCompressor` with a 3-way radio
- State: `_formMode: "standard" | "compressor" | "solar"` and `_formSolarSensor: string`.
- `_openAddForm`/`_openEditForm`: derive mode from parsed `cfg.has_compressor` / `cfg.has_solar`.
- `_renderForm`: radio group ("Single consumer" / "Heat pump (compressor + immersion)" / "Self-consuming with own solar") + threshold input (compressor only) + solar sensor input (solar only) + energy sensor input (always).
- `_saveSource`: build config JSON with `has_compressor`, `has_solar`, `solar_sensor`, and the appropriate `components` shape:
  - solar mode → `[{id: "electric_heater", name: "Electricity use"}]`, `has_compressor: false`, `has_solar: true`
  - compressor mode → existing two-component shape, `has_solar: false`
  - standard → existing single-component shape, both flags false
- `_renderSourceCard` (the breakdown row): when `has_solar`, render `solar_kwh`, `purchased_kwh`, `purchased_cost`, `solar_value` instead of the (collapsed) per-component split.

### `types.ts`
Extend `HeatSourcePeriodStats` / `HeatSourceBreakdown` with `has_solar?: boolean`, `solar_energy_kwh`, `solar_value_sek`, `purchased_kwh`, `purchased_cost_sek`.

### `localize.ts`
New `TranslationKey`s in both `en` and `sv`: `heat.modeStandard`, `heat.modeCompressor`, `heat.modeSolar`, `heat.solarSensor`, `heat.solarKwh`, `heat.solarValue`, `heat.purchasedKwh`, `heat.purchasedCost`. Match existing heat-key style.

### Build + version bump
After editing the panel, rebuild and copy:
```
cd custom_cards/my-solar-cells-panel && npm run build
cp custom_cards/my-solar-cells-panel/my-solar-cells-panel.js \
   custom_components/my_solar_cells/my-solar-cells-panel.js
```
Bump `version` in `custom_components/my_solar_cells/manifest.json` for cache-busting.

## Gotchas
1. **Solar-sensor reset detection** — same negative-delta guard the energy sensor uses today; skip on negative.
2. **`solar > total` clamp is mandatory**, not defensive — sampling jitter can produce brief overshoot when the two cumulative counters tick at slightly different times.
3. **`unit_price_sold` may be missing for the current hour** — Tibber backfills after the hour closes. Fall back to `spot_price` for the live tick; the upsert is additive, so this self-corrects on the next coordinator pass when Tibber data arrives. Backfill always has it.
4. **Yearly tax-reduction cap uses the heat-source-level purchased** (`total − solar`), not the household-level `hourly_energy.purchased`. The household export is independent of this consumer's self-consumption.
5. **Migration runs on every startup** — `PRAGMA table_info` is cheap and the ALTER branches no-op when columns already exist. Order: `executescript` first (CREATE TABLE IF NOT EXISTS gives fresh installs everything), then `_migrate_sync`.
6. **WS API server-side validation** — even with the radio in the UI, validate the parsed config in `ws_save_heat_source` and reject `has_compressor && has_solar`. Belt-and-braces.
7. **Existing rows keep working** — `has_solar` defaults to False, so any heat source row missing the new keys parses identically to today.

## Tests (`tests/`)

`test_heat_source_engine.py`:
- `test_solar_mode_parses_flags` — config with `has_solar=True, solar_sensor=...`; assert flags + single-component shape + `has_compressor==False`.
- `test_solar_mode_overrides_compressor_for_safety` — input `{has_compressor: True, has_solar: True}` → parsed config has `has_compressor=False`.
- `TestCalculateHeatSourcePeriodWithSolar` class:
  - `test_solar_aggregation_sums_solar_kwh_and_value` — feed records with the new fields, assert period totals.
  - `test_purchased_kwh_equals_energy_minus_solar` — derived field check.

`test_database_heat_sources.py`:
- `test_solar_columns_persist` — upsert with new params, read back via `get_heat_source_energy`.
- `test_solar_columns_accumulate` — two upserts to same hour bucket; solar fields accumulate additively.
- `test_alter_table_idempotent` — open/close/re-open; `_migrate_sync` doesn't fail on second run.
- `test_legacy_db_gets_solar_columns` — pre-create with old schema (no solar columns), call `_setup_sync`, assert columns now exist with NULL/0 defaults.
- Update existing summary test to assert new keys exist and default to 0 for non-solar fixtures.

Run with: `pytest tests/test_heat_source_engine.py tests/test_database_heat_sources.py -v`

## Verification (end-to-end)

1. Apply the migration on a copy of the live DB:
   ```
   sqlite3 ~/.homeassistant/.storage/my_solar_cells.db "PRAGMA table_info(heat_source_energy);"
   ```
   Confirm `solar_energy_kwh` and `solar_spot_value_sek` appear after first restart.

2. In the panel "Configuration" view, edit "Laddning bil Totalt":
   - Switch mode to "Self-consuming with own solar"
   - Set `solar_sensor = sensor.charge_car_sun_energy_total`
   - Save → existing data is wiped, backfill flag cleared.

3. Within ~15 minutes the coordinator re-backfills both sensors. Verify:
   - Heat source breakdown shows `solar_kwh > 0`, `purchased_kwh = total − solar`, `purchased_cost` lower than before, `solar_value` populated.
   - Pick a sunny hour and verify by hand: `solar_value ≈ solar_kwh × (unit_price_sold + 0.078 + 0.60)` (subject to yearly cap).

4. Try saving a heat source with both flags via crafted WS payload — assert the API rejects with `invalid_config`.

5. Delete the redundant "Ladning bil Solel" entry once the new mode confirms parity.

6. Run `pytest tests/ -v` — all green, including the new tests.
