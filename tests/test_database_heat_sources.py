"""Tests for heat source database operations."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from custom_components.energy_facts.database import EnergyFactsDatabase


class FakeConfig:
    """Minimal fake config for testing."""

    def __init__(self, tmp_dir: str):
        self._tmp_dir = tmp_dir

    def path(self, path: str) -> str:
        return os.path.join(self._tmp_dir, path)


class FakeHass:
    """Minimal fake hass for testing."""

    def __init__(self, tmp_dir: str):
        self.config = FakeConfig(tmp_dir)

    def async_add_executor_job(self, fn, *args):
        """Synchronously run the function (for testing)."""
        return fn(*args)


@pytest.fixture
def db(tmp_path):
    """Create a test database."""
    hass = FakeHass(str(tmp_path))
    database = EnergyFactsDatabase(hass, "test_entry")
    database._setup_sync()
    yield database
    database._close_sync()


class TestHeatSourceCRUD:
    """Test heat source CRUD operations."""

    def test_upsert_and_get(self, db):
        """Test creating and retrieving a heat source."""
        config = json.dumps({
            "components": [
                {"id": "heat_pump", "name": "VP"},
                {"id": "electric_heater", "name": "EP"},
            ],
            "electric_heater_threshold_w": 700,
        })
        db.upsert_heat_source(
            id="vp1",
            name="Frånluft",
            source_type="power_threshold",
            energy_sensor="sensor.energy",
            power_sensor="sensor.power",
            config=config,
        )
        db._save_sync()

        result = db.get_heat_source("vp1")
        assert result is not None
        assert result["name"] == "Frånluft"
        assert result["energy_sensor"] == "sensor.energy"
        assert result["is_active"] == 1

    def test_get_all(self, db):
        """Test listing all heat sources."""
        db.upsert_heat_source("vp1", "Source A", "power_threshold", "s.e1", "s.p1")
        db.upsert_heat_source("vp2", "Source B", "power_threshold", "s.e2", "s.p2")
        db._save_sync()

        sources = db.get_heat_sources()
        assert len(sources) == 2

    def test_update_existing(self, db):
        """Test updating an existing heat source."""
        db.upsert_heat_source("vp1", "Old Name", "power_threshold", "s.e1", "s.p1")
        db.upsert_heat_source("vp1", "New Name", "power_threshold", "s.e2", "s.p2")
        db._save_sync()

        result = db.get_heat_source("vp1")
        assert result["name"] == "New Name"
        assert result["energy_sensor"] == "s.e2"

    def test_delete_cascades(self, db):
        """Test deleting a heat source also removes energy records."""
        db.upsert_heat_source("vp1", "Test", "power_threshold", "s.e", "s.p")
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "heat_pump",
            energy_kwh=1.0, cost_sek=0.5, avg_power_w=400, spot_price=0.5, samples=1,
        )
        db._save_sync()

        db.delete_heat_source("vp1")
        db._save_sync()

        assert db.get_heat_source("vp1") is None
        records = db.get_heat_source_energy_for_period(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00", "vp1"
        )
        assert len(records) == 0

    def test_get_nonexistent(self, db):
        """Test getting a non-existent heat source returns None."""
        assert db.get_heat_source("nonexistent") is None


class TestHeatSourceEnergy:
    """Test heat source energy recording."""

    def test_insert_energy(self, db):
        """Test inserting a single energy record."""
        db.upsert_heat_source("vp1", "Test", "power_threshold", "s.e", "s.p")
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "heat_pump",
            energy_kwh=1.5, cost_sek=0.75, avg_power_w=400, spot_price=0.50, samples=1,
        )
        db._save_sync()

        result = db.get_heat_source_energy("vp1", "heat_pump", "2025-01-01T10:00:00")
        assert result is not None
        assert result["energy_kwh"] == pytest.approx(1.5)
        assert result["cost_sek"] == pytest.approx(0.75)
        assert result["samples"] == 1

    def test_accumulate_energy(self, db):
        """Test that multiple inserts accumulate within the same hour."""
        db.upsert_heat_source("vp1", "Test", "power_threshold", "s.e", "s.p")
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "heat_pump",
            energy_kwh=1.0, cost_sek=0.50, avg_power_w=400, spot_price=0.50, samples=1,
        )
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "heat_pump",
            energy_kwh=0.5, cost_sek=0.25, avg_power_w=450, spot_price=0.50, samples=1,
        )
        db._save_sync()

        result = db.get_heat_source_energy("vp1", "heat_pump", "2025-01-01T10:00:00")
        assert result["energy_kwh"] == pytest.approx(1.5)
        assert result["cost_sek"] == pytest.approx(0.75)
        assert result["samples"] == 2
        # Weighted average: (400*1 + 450*1) / 2 = 425
        assert result["avg_power_w"] == pytest.approx(425.0)

    def test_period_query(self, db):
        """Test querying energy for a period."""
        db.upsert_heat_source("vp1", "Test", "power_threshold", "s.e", "s.p")
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "heat_pump",
            energy_kwh=1.0, cost_sek=0.50, avg_power_w=400, spot_price=0.50, samples=1,
        )
        db.upsert_heat_source_energy(
            "2025-01-01T11:00:00", "vp1", "electric_heater",
            energy_kwh=2.0, cost_sek=1.00, avg_power_w=1200, spot_price=0.50, samples=1,
        )
        db.upsert_heat_source_energy(
            "2025-01-02T10:00:00", "vp1", "heat_pump",
            energy_kwh=1.0, cost_sek=0.50, avg_power_w=400, spot_price=0.50, samples=1,
        )
        db._save_sync()

        records = db.get_heat_source_energy_for_period(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00"
        )
        assert len(records) == 2

    def test_period_query_with_source_filter(self, db):
        """Test querying with heat_source_id filter."""
        db.upsert_heat_source("vp1", "Source 1", "power_threshold", "s.e1", "s.p1")
        db.upsert_heat_source("vp2", "Source 2", "power_threshold", "s.e2", "s.p2")
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "heat_pump",
            energy_kwh=1.0, cost_sek=0.50, avg_power_w=400, spot_price=0.50, samples=1,
        )
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp2", "heat_pump",
            energy_kwh=2.0, cost_sek=1.00, avg_power_w=500, spot_price=0.50, samples=1,
        )
        db._save_sync()

        records = db.get_heat_source_energy_for_period(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00", "vp1"
        )
        assert len(records) == 1
        assert records[0]["heat_source_id"] == "vp1"


class TestHeatSourceEnergySummary:
    """Test heat source energy summary aggregation."""

    def test_summary_aggregation(self, db):
        """Test SQL aggregation for summary."""
        db.upsert_heat_source("vp1", "Test", "power_threshold", "s.e", "s.p")
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "heat_pump",
            energy_kwh=1.0, cost_sek=0.50, avg_power_w=400, spot_price=0.50, samples=1,
        )
        db.upsert_heat_source_energy(
            "2025-01-01T11:00:00", "vp1", "heat_pump",
            energy_kwh=1.5, cost_sek=0.75, avg_power_w=450, spot_price=0.50, samples=1,
        )
        db.upsert_heat_source_energy(
            "2025-01-01T10:00:00", "vp1", "electric_heater",
            energy_kwh=3.0, cost_sek=1.50, avg_power_w=1200, spot_price=0.50, samples=1,
        )
        db._save_sync()

        summary = db.get_heat_source_energy_summary(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00"
        )
        components = summary["components"]
        assert len(components) == 2

        hp = next(c for c in components if c["component"] == "heat_pump")
        assert hp["total_energy_kwh"] == pytest.approx(2.5)
        assert hp["total_cost_sek"] == pytest.approx(1.25)

        eh = next(c for c in components if c["component"] == "electric_heater")
        assert eh["total_energy_kwh"] == pytest.approx(3.0)

    def test_summary_empty(self, db):
        """Test summary with no data."""
        summary = db.get_heat_source_energy_summary(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00"
        )
        assert summary["components"] == []


class TestHeatSourceReadingsMetadata:
    """Test last_heat_source_readings property."""

    def test_empty_default(self, db):
        """Test default returns empty dict."""
        assert db.last_heat_source_readings == {}

    def test_set_and_get(self, db):
        """Test storing and retrieving readings."""
        readings = {"energy_vp1": 12345.67}
        db.last_heat_source_readings = readings
        db._save_sync()

        result = db.last_heat_source_readings
        assert result["energy_vp1"] == pytest.approx(12345.67)


class TestSolarEnergyColumns:
    """Test solar columns in heat_source_energy."""

    def test_solar_columns_persist(self, db):
        """Solar energy and spot value are stored and retrieved."""
        db.upsert_heat_source("car1", "Car", "power_threshold", "s.e", "")
        db.upsert_heat_source_energy(
            "2025-06-01T10:00:00", "car1", "electric_heater",
            energy_kwh=1.5, cost_sek=0.75, avg_power_w=300, spot_price=0.50, samples=1,
            solar_energy_kwh=0.5, solar_spot_value_sek=0.20,
        )
        db._save_sync()

        rec = db.get_heat_source_energy("car1", "electric_heater", "2025-06-01T10:00:00")
        assert rec is not None
        assert rec["solar_energy_kwh"] == pytest.approx(0.5)
        assert rec["solar_spot_value_sek"] == pytest.approx(0.20)

    def test_solar_columns_accumulate(self, db):
        """Two upserts to the same hour bucket accumulate solar fields additively."""
        db.upsert_heat_source("car1", "Car", "power_threshold", "s.e", "")
        db.upsert_heat_source_energy(
            "2025-06-01T10:00:00", "car1", "electric_heater",
            energy_kwh=1.0, cost_sek=0.50, avg_power_w=300, spot_price=0.50, samples=1,
            solar_energy_kwh=0.3, solar_spot_value_sek=0.12,
        )
        db.upsert_heat_source_energy(
            "2025-06-01T10:00:00", "car1", "electric_heater",
            energy_kwh=0.5, cost_sek=0.25, avg_power_w=250, spot_price=0.50, samples=1,
            solar_energy_kwh=0.2, solar_spot_value_sek=0.08,
        )
        db._save_sync()

        rec = db.get_heat_source_energy("car1", "electric_heater", "2025-06-01T10:00:00")
        assert rec["solar_energy_kwh"] == pytest.approx(0.5)
        assert rec["solar_spot_value_sek"] == pytest.approx(0.20)

    def test_alter_table_idempotent(self, db):
        """Running _migrate_sync twice does not raise an error."""
        db._migrate_sync()  # second call on already-migrated DB
        db._migrate_sync()  # third call — should also be harmless
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(heat_source_energy)").fetchall()}
        assert "solar_energy_kwh" in cols
        assert "solar_spot_value_sek" in cols

    def test_legacy_db_gets_solar_columns(self, tmp_path):
        """A DB created without solar columns gets them added by _migrate_sync."""
        import sqlite3
        db_path = str(tmp_path / ".storage" / "legacy.db")
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Create old schema without solar columns
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE heat_source_energy (
                timestamp TEXT NOT NULL,
                heat_source_id TEXT NOT NULL,
                component TEXT NOT NULL,
                energy_kwh REAL DEFAULT 0,
                cost_sek REAL DEFAULT 0,
                avg_power_w REAL DEFAULT 0,
                spot_price REAL DEFAULT 0,
                samples INTEGER DEFAULT 0,
                PRIMARY KEY (timestamp, heat_source_id, component)
            )
        """)
        conn.commit()
        conn.close()

        # Re-open via EnergyFactsDatabase — _migrate_sync should add columns
        hass = FakeHass(str(tmp_path))
        database = EnergyFactsDatabase.__new__(EnergyFactsDatabase)
        database._hass = hass
        database._entry_id = "legacy"
        database._db_path = db_path
        database._conn = None
        import sqlite3 as _sq
        database._conn = _sq.connect(db_path, check_same_thread=False)
        database._conn.row_factory = _sq.Row
        database._migrate_sync()

        cols = {row[1] for row in database._conn.execute("PRAGMA table_info(heat_source_energy)").fetchall()}
        assert "solar_energy_kwh" in cols
        assert "solar_spot_value_sek" in cols
        database._conn.close()

    def test_summary_includes_solar_columns(self, db):
        """get_heat_source_energy_summary returns solar aggregate columns."""
        db.upsert_heat_source("car1", "Car", "power_threshold", "s.e", "")
        db.upsert_heat_source_energy(
            "2025-06-01T10:00:00", "car1", "electric_heater",
            energy_kwh=1.0, cost_sek=0.50, avg_power_w=300, spot_price=0.50, samples=1,
            solar_energy_kwh=0.4, solar_spot_value_sek=0.16,
        )
        db.upsert_heat_source_energy(
            "2025-06-01T11:00:00", "car1", "electric_heater",
            energy_kwh=0.5, cost_sek=0.25, avg_power_w=200, spot_price=0.50, samples=1,
            solar_energy_kwh=0.1, solar_spot_value_sek=0.04,
        )
        db._save_sync()

        summary = db.get_heat_source_energy_summary(
            "2025-06-01T00:00:00", "2025-06-02T00:00:00"
        )
        comps = summary["components"]
        assert len(comps) == 1
        c = comps[0]
        assert c["total_solar_energy_kwh"] == pytest.approx(0.5)
        assert c["total_solar_spot_value_sek"] == pytest.approx(0.20)

    def test_get_unit_price_sold_for_hour(self, db):
        """get_unit_price_sold_for_hour returns value from hourly_energy."""
        db.upsert_hourly_record("2025-06-01T10:00:00", {
            "unit_price_sold": 0.85,
            "unit_price_buy": 1.20,
        })
        db._save_sync()

        result = db.get_unit_price_sold_for_hour("2025-06-01T10")
        assert result == pytest.approx(0.85)

    def test_get_unit_price_sold_missing(self, db):
        """get_unit_price_sold_for_hour returns None when no record exists."""
        result = db.get_unit_price_sold_for_hour("2025-06-01T10")
        assert result is None
