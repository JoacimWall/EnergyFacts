"""SQLite database manager for EnergyFacts."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hourly_energy (
    timestamp TEXT PRIMARY KEY,
    purchased REAL DEFAULT 0,
    purchased_cost REAL DEFAULT 0,
    production_sold REAL DEFAULT 0,
    production_sold_profit REAL DEFAULT 0,
    unit_price_buy REAL DEFAULT 0,
    unit_price_vat_buy REAL DEFAULT 0,
    unit_price_sold REAL DEFAULT 0,
    unit_price_vat_sold REAL DEFAULT 0,
    production_own_use REAL DEFAULT 0,
    production_own_use_profit REAL DEFAULT 0,
    battery_charge REAL DEFAULT 0,
    battery_used REAL DEFAULT 0,
    battery_used_profit REAL DEFAULT 0,
    synced INTEGER DEFAULT 0,
    sensor_enriched INTEGER DEFAULT 0,
    price_level TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS spot_prices (
    timestamp TEXT PRIMARY KEY,
    total REAL DEFAULT 0,
    energy REAL DEFAULT 0,
    tax REAL DEFAULT 0,
    level TEXT DEFAULT '',
    currency TEXT DEFAULT 'SEK'
);

CREATE TABLE IF NOT EXISTS yearly_params (
    year INTEGER PRIMARY KEY,
    tax_reduction REAL,
    grid_compensation REAL,
    transfer_fee REAL,
    energy_tax REAL,
    installed_kw REAL
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS heat_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'power_threshold',
    energy_sensor TEXT NOT NULL,
    power_sensor TEXT NOT NULL DEFAULT '',
    config TEXT DEFAULT '{}',
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS heat_source_energy (
    timestamp TEXT NOT NULL,
    heat_source_id TEXT NOT NULL,
    component TEXT NOT NULL,
    energy_kwh REAL DEFAULT 0,
    cost_sek REAL DEFAULT 0,
    avg_power_w REAL DEFAULT 0,
    spot_price REAL DEFAULT 0,
    samples INTEGER DEFAULT 0,
    solar_energy_kwh REAL DEFAULT 0,
    solar_spot_value_sek REAL DEFAULT 0,
    PRIMARY KEY (timestamp, heat_source_id, component),
    FOREIGN KEY (heat_source_id) REFERENCES heat_sources(id)
);
"""

# Column names for hourly_energy table (order must match INSERT statement)
_HOURLY_COLS = [
    "timestamp", "purchased", "purchased_cost", "production_sold",
    "production_sold_profit", "unit_price_buy", "unit_price_vat_buy",
    "unit_price_sold", "unit_price_vat_sold", "production_own_use",
    "production_own_use_profit", "battery_charge", "battery_used",
    "battery_used_profit", "synced", "sensor_enriched", "price_level",
]

_SPOT_COLS = ["timestamp", "total", "energy", "tax", "level", "currency"]


class EnergyFactsDatabase:
    """SQLite-backed storage replacing the old JSON Store."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._db_path: str = hass.config.path(f".storage/energy_facts_{entry_id}.db")
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Create connection and tables."""
        await self._hass.async_add_executor_job(self._setup_sync)

    def _setup_sync(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        self._migrate_sync()

    def _migrate_sync(self) -> None:
        """Add columns to existing databases that predate the solar feature."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(heat_source_energy)").fetchall()}
        if "solar_energy_kwh" not in cols:
            self._conn.execute("ALTER TABLE heat_source_energy ADD COLUMN solar_energy_kwh REAL DEFAULT 0")
        if "solar_spot_value_sek" not in cols:
            self._conn.execute("ALTER TABLE heat_source_energy ADD COLUMN solar_spot_value_sek REAL DEFAULT 0")
        self._conn.commit()

    async def async_close(self) -> None:
        """Close the database connection."""
        await self._hass.async_add_executor_job(self._close_sync)

    def _close_sync(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Hourly energy records
    # ------------------------------------------------------------------

    def upsert_hourly_record(self, timestamp: str, record: dict) -> None:
        """Insert or replace an hourly energy record."""
        assert self._conn is not None
        values = (
            timestamp,
            record.get("purchased", 0),
            record.get("purchased_cost", 0),
            record.get("production_sold", 0),
            record.get("production_sold_profit", 0),
            record.get("unit_price_buy", 0),
            record.get("unit_price_vat_buy", 0),
            record.get("unit_price_sold", 0),
            record.get("unit_price_vat_sold", 0),
            record.get("production_own_use", 0),
            record.get("production_own_use_profit", 0),
            record.get("battery_charge", 0),
            record.get("battery_used", 0),
            record.get("battery_used_profit", 0),
            1 if record.get("synced") else 0,
            1 if record.get("sensor_enriched") else 0,
            record.get("price_level", ""),
        )
        placeholders = ",".join("?" * len(_HOURLY_COLS))
        self._conn.execute(
            f"INSERT OR REPLACE INTO hourly_energy ({','.join(_HOURLY_COLS)}) "
            f"VALUES ({placeholders})",
            values,
        )

    def get_hourly_record(self, timestamp: str) -> dict | None:
        """Get a single hourly record by timestamp."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM hourly_energy WHERE timestamp = ?", (timestamp,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_records_for_period(self, start_iso: str, end_iso: str) -> list[dict]:
        """Get hourly records in [start_iso, end_iso)."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM hourly_energy WHERE timestamp >= ? AND timestamp < ? "
            "ORDER BY timestamp",
            (start_iso, end_iso),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_all_records_as_list(self) -> list[dict]:
        """Get all hourly records sorted by timestamp."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM hourly_energy ORDER BY timestamp"
        )
        return [dict(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Spot prices
    # ------------------------------------------------------------------

    def upsert_quarter_hourly_price(self, timestamp: str, price: dict) -> None:
        """Insert or replace a quarter-hourly spot price."""
        assert self._conn is not None
        values = (
            timestamp,
            price.get("total", 0),
            price.get("energy", 0),
            price.get("tax", 0),
            price.get("level", ""),
            price.get("currency", "SEK"),
        )
        placeholders = ",".join("?" * len(_SPOT_COLS))
        self._conn.execute(
            f"INSERT OR REPLACE INTO spot_prices ({','.join(_SPOT_COLS)}) "
            f"VALUES ({placeholders})",
            values,
        )

    def get_prices_for_date(self, date_iso: str) -> list[dict]:
        """Get all quarter-hourly prices for a date (YYYY-MM-DD)."""
        assert self._conn is not None
        prefix = f"{date_iso}%"
        cur = self._conn.execute(
            "SELECT * FROM spot_prices WHERE timestamp LIKE ? ORDER BY timestamp",
            (prefix,),
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["starts_at"] = d.pop("timestamp")
            result.append(d)
        return result

    def get_first_spot_timestamp(self) -> str | None:
        """Get the earliest spot price timestamp."""
        assert self._conn is not None
        cur = self._conn.execute("SELECT MIN(timestamp) as ts FROM spot_prices")
        row = cur.fetchone()
        return row["ts"] if row else None

    def get_average_price_for_hour(self, hour_iso: str) -> float | None:
        """Get average of quarter-hourly prices for an hour.

        hour_iso should be like "2025-06-15T14" (first 13 chars).
        Falls back to hourly_energy.unit_price_buy if spot_prices has no data.
        """
        assert self._conn is not None
        prefix = f"{hour_iso[:13]}%"
        cur = self._conn.execute(
            "SELECT AVG(total) as avg_total FROM spot_prices WHERE timestamp LIKE ?",
            (prefix,),
        )
        row = cur.fetchone()
        if row and row["avg_total"] is not None:
            return row["avg_total"]

        # Fallback: use unit_price_buy from hourly_energy for hours before
        # spot_prices were collected (e.g. historical Tibber import data)
        cur = self._conn.execute(
            "SELECT unit_price_buy FROM hourly_energy WHERE timestamp LIKE ?",
            (prefix,),
        )
        row = cur.fetchone()
        if row and row["unit_price_buy"]:
            return row["unit_price_buy"]
        return None

    # ------------------------------------------------------------------
    # Metadata (key-value store)
    # ------------------------------------------------------------------

    def _get_meta(self, key: str) -> str | None:
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        )
        row = cur.fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str | None) -> None:
        assert self._conn is not None
        if value is None:
            self._conn.execute("DELETE FROM metadata WHERE key = ?", (key,))
        else:
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )

    @property
    def last_tibber_sync(self) -> str | None:
        return self._get_meta("last_tibber_sync")

    @last_tibber_sync.setter
    def last_tibber_sync(self, value: str | None) -> None:
        self._set_meta("last_tibber_sync", value)

    @property
    def last_sensor_readings(self) -> dict[str, float]:
        raw = self._get_meta("last_sensor_readings")
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @last_sensor_readings.setter
    def last_sensor_readings(self, value: dict[str, float]) -> None:
        self._set_meta("last_sensor_readings", json.dumps(value))

    @property
    def roi_projection(self) -> list[dict]:
        raw = self._get_meta("roi_projection")
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    @roi_projection.setter
    def roi_projection(self, value: list[dict]) -> None:
        self._set_meta("roi_projection", json.dumps(value))

    @property
    def last_roi_params(self) -> dict:
        raw = self._get_meta("last_roi_params")
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @last_roi_params.setter
    def last_roi_params(self, value: dict) -> None:
        self._set_meta("last_roi_params", json.dumps(value))

    @property
    def monthly_cache(self) -> dict:
        raw = self._get_meta("monthly_cache")
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def update_monthly_cache(self, month_key: str, stats: dict) -> None:
        """Update a single month in the monthly cache."""
        cache = self.monthly_cache
        cache[month_key] = stats
        self._set_meta("monthly_cache", json.dumps(cache))

    # ------------------------------------------------------------------
    # Yearly financial parameters
    # ------------------------------------------------------------------

    _YEARLY_PARAM_COLS = [
        "tax_reduction", "grid_compensation", "transfer_fee", "energy_tax",
        "installed_kw",
    ]

    def set_yearly_params(self, year: int, params: dict) -> None:
        """Insert or replace financial parameters for a specific year."""
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO yearly_params "
            "(year, tax_reduction, grid_compensation, transfer_fee, energy_tax, "
            "installed_kw) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                year,
                params.get("tax_reduction"),
                params.get("grid_compensation"),
                params.get("transfer_fee"),
                params.get("energy_tax"),
                params.get("installed_kw"),
            ),
        )

    def get_yearly_params(self, year: int) -> dict | None:
        """Get financial parameters for a specific year, or None if not set."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM yearly_params WHERE year = ?", (year,)
        )
        row = cur.fetchone()
        if not row:
            return None
        result = {}
        for col in self._YEARLY_PARAM_COLS:
            val = row[col]
            if val is not None:
                result[col] = val
        return result if result else None

    def get_all_yearly_params(self) -> dict[str, dict]:
        """Get all yearly params as dict keyed by year string.

        Compatible with the format expected by get_calc_params_for_year().
        """
        assert self._conn is not None
        cur = self._conn.execute("SELECT * FROM yearly_params ORDER BY year")
        result: dict[str, dict] = {}
        for row in cur.fetchall():
            params = {}
            for col in self._YEARLY_PARAM_COLS:
                val = row[col]
                if val is not None:
                    params[col] = val
            if params:
                result[str(row["year"])] = params
        return result

    def delete_yearly_params(self, year: int) -> None:
        """Delete financial parameters for a specific year."""
        assert self._conn is not None
        self._conn.execute("DELETE FROM yearly_params WHERE year = ?", (year,))

    # ------------------------------------------------------------------
    # Heat sources
    # ------------------------------------------------------------------

    def upsert_heat_source(
        self,
        id: str,
        name: str,
        source_type: str,
        energy_sensor: str,
        power_sensor: str,
        config: str = "{}",
        is_active: int = 1,
    ) -> None:
        """Insert or replace a heat source configuration."""
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO heat_sources "
            "(id, name, source_type, energy_sensor, power_sensor, config, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, name, source_type, energy_sensor, power_sensor, config, is_active),
        )

    def get_heat_sources(self) -> list[dict]:
        """Get all heat sources."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM heat_sources ORDER BY name"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_heat_source(self, id: str) -> dict | None:
        """Get a single heat source by id."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM heat_sources WHERE id = ?", (id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def delete_heat_source(self, id: str) -> None:
        """Delete a heat source and its energy records."""
        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM heat_source_energy WHERE heat_source_id = ?", (id,)
        )
        self._conn.execute(
            "DELETE FROM heat_sources WHERE id = ?", (id,)
        )

    def upsert_heat_source_energy(
        self,
        timestamp: str,
        heat_source_id: str,
        component: str,
        energy_kwh: float,
        cost_sek: float,
        avg_power_w: float,
        spot_price: float,
        samples: int,
        solar_energy_kwh: float = 0.0,
        solar_spot_value_sek: float = 0.0,
    ) -> None:
        """Insert or accumulate heat source energy within an hour bucket."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT energy_kwh, cost_sek, avg_power_w, spot_price, samples, "
            "solar_energy_kwh, solar_spot_value_sek "
            "FROM heat_source_energy "
            "WHERE timestamp = ? AND heat_source_id = ? AND component = ?",
            (timestamp, heat_source_id, component),
        )
        row = cur.fetchone()
        if row:
            new_samples = row["samples"] + samples
            new_energy = row["energy_kwh"] + energy_kwh
            new_cost = row["cost_sek"] + cost_sek
            new_solar_kwh = (row["solar_energy_kwh"] or 0) + solar_energy_kwh
            new_solar_spot = (row["solar_spot_value_sek"] or 0) + solar_spot_value_sek
            if new_samples > 0:
                new_avg_power = (
                    row["avg_power_w"] * row["samples"] + avg_power_w * samples
                ) / new_samples
            else:
                new_avg_power = avg_power_w
            new_spot = spot_price
            self._conn.execute(
                "UPDATE heat_source_energy SET "
                "energy_kwh = ?, cost_sek = ?, avg_power_w = ?, spot_price = ?, samples = ?, "
                "solar_energy_kwh = ?, solar_spot_value_sek = ? "
                "WHERE timestamp = ? AND heat_source_id = ? AND component = ?",
                (new_energy, new_cost, new_avg_power, new_spot, new_samples,
                 new_solar_kwh, new_solar_spot,
                 timestamp, heat_source_id, component),
            )
        else:
            self._conn.execute(
                "INSERT INTO heat_source_energy "
                "(timestamp, heat_source_id, component, energy_kwh, cost_sek, "
                "avg_power_w, spot_price, samples, solar_energy_kwh, solar_spot_value_sek) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (timestamp, heat_source_id, component, energy_kwh, cost_sek,
                 avg_power_w, spot_price, samples, solar_energy_kwh, solar_spot_value_sek),
            )

    def delete_heat_source_energy_for_source(self, heat_source_id: str) -> None:
        """Delete all energy records for a heat source (used before re-backfill)."""
        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM heat_source_energy WHERE heat_source_id = ?",
            (heat_source_id,),
        )

    def get_heat_source_energy(
        self, heat_source_id: str, component: str, timestamp: str
    ) -> dict | None:
        """Get a single heat source energy record."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM heat_source_energy "
            "WHERE heat_source_id = ? AND component = ? AND timestamp = ?",
            (heat_source_id, component, timestamp),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_heat_source_energy_paginated(
        self,
        start_iso: str,
        end_iso: str,
        offset: int = 0,
        limit: int = 50,
        heat_source_id: str | None = None,
    ) -> tuple[list[dict], int]:
        """Get paginated heat source energy records in [start_iso, end_iso) with total count."""
        assert self._conn is not None
        if heat_source_id:
            cur = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM heat_source_energy "
                "WHERE timestamp >= ? AND timestamp < ? AND heat_source_id = ?",
                (start_iso, end_iso, heat_source_id),
            )
            total = cur.fetchone()["cnt"]
            cur = self._conn.execute(
                "SELECT * FROM heat_source_energy "
                "WHERE timestamp >= ? AND timestamp < ? AND heat_source_id = ? "
                "ORDER BY timestamp, heat_source_id, component LIMIT ? OFFSET ?",
                (start_iso, end_iso, heat_source_id, limit, offset),
            )
        else:
            cur = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM heat_source_energy "
                "WHERE timestamp >= ? AND timestamp < ?",
                (start_iso, end_iso),
            )
            total = cur.fetchone()["cnt"]
            cur = self._conn.execute(
                "SELECT * FROM heat_source_energy "
                "WHERE timestamp >= ? AND timestamp < ? "
                "ORDER BY timestamp, heat_source_id, component LIMIT ? OFFSET ?",
                (start_iso, end_iso, limit, offset),
            )
        records = [dict(row) for row in cur.fetchall()]
        return records, total

    def get_heat_source_energy_for_period(
        self, start_iso: str, end_iso: str, heat_source_id: str | None = None
    ) -> list[dict]:
        """Get heat source energy records for a period."""
        assert self._conn is not None
        if heat_source_id:
            cur = self._conn.execute(
                "SELECT * FROM heat_source_energy "
                "WHERE timestamp >= ? AND timestamp < ? AND heat_source_id = ? "
                "ORDER BY timestamp",
                (start_iso, end_iso, heat_source_id),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM heat_source_energy "
                "WHERE timestamp >= ? AND timestamp < ? "
                "ORDER BY timestamp",
                (start_iso, end_iso),
            )
        return [dict(row) for row in cur.fetchall()]

    def get_heat_source_energy_summary(
        self, start_iso: str, end_iso: str, heat_source_id: str | None = None
    ) -> dict:
        """Get aggregated heat source energy summary for a period."""
        assert self._conn is not None
        select = (
            "SELECT heat_source_id, component, "
            "COALESCE(SUM(energy_kwh), 0) AS total_energy_kwh, "
            "COALESCE(SUM(cost_sek), 0) AS total_cost_sek, "
            "COALESCE(AVG(avg_power_w), 0) AS avg_power_w, "
            "COALESCE(SUM(solar_energy_kwh), 0) AS total_solar_energy_kwh, "
            "COALESCE(SUM(solar_spot_value_sek), 0) AS total_solar_spot_value_sek "
            "FROM heat_source_energy "
        )
        if heat_source_id:
            cur = self._conn.execute(
                select + "WHERE timestamp >= ? AND timestamp < ? AND heat_source_id = ? "
                "GROUP BY heat_source_id, component",
                (start_iso, end_iso, heat_source_id),
            )
        else:
            cur = self._conn.execute(
                select + "WHERE timestamp >= ? AND timestamp < ? "
                "GROUP BY heat_source_id, component",
                (start_iso, end_iso),
            )
        rows = [dict(row) for row in cur.fetchall()]
        return {"components": rows}

    def get_unit_price_sold_for_hour(self, hour_iso: str) -> float | None:
        """Get unit_price_sold from hourly_energy for an hour.

        hour_iso should be like "2025-06-15T14" (first 13 chars).
        """
        assert self._conn is not None
        prefix = f"{hour_iso[:13]}%"
        cur = self._conn.execute(
            "SELECT unit_price_sold FROM hourly_energy WHERE timestamp LIKE ? LIMIT 1",
            (prefix,),
        )
        row = cur.fetchone()
        if row and row["unit_price_sold"]:
            return row["unit_price_sold"]
        return None

    @property
    def last_heat_source_readings(self) -> dict:
        raw = self._get_meta("last_heat_source_readings")
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @last_heat_source_readings.setter
    def last_heat_source_readings(self, value: dict) -> None:
        self._set_meta("last_heat_source_readings", json.dumps(value))

    # ------------------------------------------------------------------
    # Panel query helpers
    # ------------------------------------------------------------------

    def get_hourly_record_count(self) -> int:
        """Get total number of hourly energy records."""
        assert self._conn is not None
        cur = self._conn.execute("SELECT COUNT(*) as cnt FROM hourly_energy")
        return cur.fetchone()["cnt"]

    def get_first_hourly_timestamp(self) -> str | None:
        """Get the earliest hourly energy timestamp."""
        assert self._conn is not None
        cur = self._conn.execute("SELECT MIN(timestamp) as ts FROM hourly_energy")
        row = cur.fetchone()
        return row["ts"] if row else None

    def get_last_hourly_timestamp(self) -> str | None:
        """Get the latest hourly energy timestamp."""
        assert self._conn is not None
        cur = self._conn.execute("SELECT MAX(timestamp) as ts FROM hourly_energy")
        row = cur.fetchone()
        return row["ts"] if row else None

    def get_records_for_period_paginated(
        self, start_iso: str, end_iso: str, offset: int = 0, limit: int = 50
    ) -> tuple[list[dict], int]:
        """Get paginated hourly records in [start_iso, end_iso) with total count."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM hourly_energy "
            "WHERE timestamp >= ? AND timestamp < ?",
            (start_iso, end_iso),
        )
        total = cur.fetchone()["cnt"]
        cur = self._conn.execute(
            "SELECT * FROM hourly_energy WHERE timestamp >= ? AND timestamp < ? "
            "ORDER BY timestamp LIMIT ? OFFSET ?",
            (start_iso, end_iso, limit, offset),
        )
        records = [dict(row) for row in cur.fetchall()]
        return records, total

    def get_unenriched_records(self) -> list[dict]:
        """Get all hourly records that have not been sensor-enriched."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM hourly_energy WHERE sensor_enriched = 0 "
            "ORDER BY timestamp"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_period_summary(self, start_iso: str, end_iso: str) -> dict:
        """Get aggregated energy summary for a period [start_iso, end_iso)."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT "
            "COALESCE(SUM(production_own_use), 0) AS own_use_kwh, "
            "COALESCE(SUM(production_own_use_profit), 0) AS own_use_sek, "
            "COALESCE(SUM(production_sold), 0) AS sold_kwh, "
            "COALESCE(SUM(production_sold_profit), 0) AS sold_sek "
            "FROM hourly_energy WHERE timestamp >= ? AND timestamp < ?",
            (start_iso, end_iso),
        )
        row = cur.fetchone()
        return {
            "own_use_kwh": row["own_use_kwh"],
            "own_use_sek": row["own_use_sek"],
            "sold_kwh": row["sold_kwh"],
            "sold_sek": row["sold_sek"],
        }

    def get_price_level_for_hour(self, hour_iso: str) -> str:
        """Get the price level from the first spot price matching an hour."""
        assert self._conn is not None
        prefix = f"{hour_iso[:13]}%"
        cur = self._conn.execute(
            "SELECT level FROM spot_prices WHERE timestamp LIKE ? LIMIT 1",
            (prefix,),
        )
        row = cur.fetchone()
        return row["level"] if row and row["level"] else ""

    # ------------------------------------------------------------------
    # Save / Remove
    # ------------------------------------------------------------------

    async def async_save(self) -> None:
        """Commit pending changes."""
        await self._hass.async_add_executor_job(self._save_sync)

    def _save_sync(self) -> None:
        if self._conn:
            self._conn.commit()

    async def async_remove(self) -> None:
        """Close connection and delete the database file."""
        await self._hass.async_add_executor_job(self._remove_sync)

    def _remove_sync(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        if os.path.exists(self._db_path):
            os.remove(self._db_path)
            _LOGGER.info("Removed database file: %s", self._db_path)
