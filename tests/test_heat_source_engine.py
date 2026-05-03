"""Tests for the heat source energy calculation engine."""

from __future__ import annotations

import pytest

from custom_components.my_solar_cells.heat_source_engine import (
    ComponentEnergySplit,
    HeatSourceConfig,
    calculate_heat_source_period,
    load_heat_source_config,
    split_energy_by_power,
)


@pytest.fixture
def default_config() -> HeatSourceConfig:
    """Return a default heat source config."""
    return HeatSourceConfig(
        id="vp1",
        name="Frånluftsvärmepump",
        energy_sensor="sensor.shelly_energy",
        power_sensor="sensor.shelly_power",
        components=[
            {"id": "heat_pump", "name": "Värmepump"},
            {"id": "electric_heater", "name": "Elpatron"},
        ],
        electric_heater_threshold_w=700.0,
    )


class TestSplitEnergyByPower:
    """Tests for split_energy_by_power."""

    def test_below_threshold_all_to_heat_pump(self, default_config):
        """When power is below threshold, all energy goes to heat_pump."""
        splits = split_energy_by_power(500.0, 1.0, default_config)
        assert len(splits) == 2
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        assert hp.energy_kwh == 1.0
        assert hp.power_w == 500.0
        assert eh.energy_kwh == 0
        assert eh.power_w == 0

    def test_at_threshold_all_to_heat_pump(self, default_config):
        """When power is exactly at threshold - 1, all goes to heat_pump."""
        splits = split_energy_by_power(699.0, 2.0, default_config)
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        assert hp.energy_kwh == 2.0
        assert eh.energy_kwh == 0

    def test_above_threshold_split(self, default_config):
        """When power >= threshold, energy is split proportionally."""
        # 1400W total, threshold 700W → 50/50 split
        splits = split_energy_by_power(1400.0, 2.0, default_config)
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        assert hp.energy_kwh == pytest.approx(1.0)
        assert hp.power_w == pytest.approx(700.0)
        assert eh.energy_kwh == pytest.approx(1.0)
        assert eh.power_w == pytest.approx(700.0)

    def test_exactly_at_threshold(self, default_config):
        """When power equals threshold exactly, split occurs."""
        splits = split_energy_by_power(700.0, 1.0, default_config)
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        # ratio = 700/700 = 1.0 → all to heat_pump, 0 to heater
        assert hp.energy_kwh == pytest.approx(1.0)
        assert eh.energy_kwh == pytest.approx(0.0)

    def test_high_power_split(self, default_config):
        """Test with very high power (3500W)."""
        # threshold=700, ratio=700/3500=0.2
        splits = split_energy_by_power(3500.0, 5.0, default_config)
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        assert hp.energy_kwh == pytest.approx(1.0)
        assert hp.power_w == pytest.approx(700.0)
        assert eh.energy_kwh == pytest.approx(4.0)
        assert eh.power_w == pytest.approx(2800.0)

    def test_zero_power(self, default_config):
        """Zero power results in zero energy for both."""
        splits = split_energy_by_power(0.0, 1.0, default_config)
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        assert hp.energy_kwh == 0
        assert eh.energy_kwh == 0

    def test_zero_energy_delta(self, default_config):
        """Zero energy delta results in zero for both."""
        splits = split_energy_by_power(500.0, 0.0, default_config)
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        assert hp.energy_kwh == 0
        assert eh.energy_kwh == 0

    def test_negative_power(self, default_config):
        """Negative power results in zero for both."""
        splits = split_energy_by_power(-100.0, 1.0, default_config)
        hp = next(s for s in splits if s.component == "heat_pump")
        assert hp.energy_kwh == 0

    def test_custom_threshold(self):
        """Test with a custom threshold value."""
        config = HeatSourceConfig(
            id="vp1",
            name="Test",
            energy_sensor="sensor.e",
            power_sensor="sensor.p",
            electric_heater_threshold_w=500.0,
        )
        # 1000W, threshold 500 → 50/50
        splits = split_energy_by_power(1000.0, 4.0, config)
        hp = next(s for s in splits if s.component == "heat_pump")
        eh = next(s for s in splits if s.component == "electric_heater")
        assert hp.energy_kwh == pytest.approx(2.0)
        assert eh.energy_kwh == pytest.approx(2.0)


class TestCalculateHeatSourcePeriod:
    """Tests for calculate_heat_source_period."""

    def test_empty_records(self):
        """Empty records returns empty list."""
        result = calculate_heat_source_period([], [])
        assert result == []

    def test_single_source_aggregation(self):
        """Test aggregation for a single heat source."""
        records = [
            {
                "heat_source_id": "vp1",
                "component": "heat_pump",
                "energy_kwh": 1.5,
                "cost_sek": 0.75,
                "avg_power_w": 400.0,
            },
            {
                "heat_source_id": "vp1",
                "component": "heat_pump",
                "energy_kwh": 2.0,
                "cost_sek": 1.20,
                "avg_power_w": 450.0,
            },
            {
                "heat_source_id": "vp1",
                "component": "electric_heater",
                "energy_kwh": 3.0,
                "cost_sek": 1.80,
                "avg_power_w": 1200.0,
            },
        ]
        sources = [
            {
                "id": "vp1",
                "name": "Värmepump",
                "config": '{"components": [{"id": "heat_pump", "name": "VP"}, {"id": "electric_heater", "name": "EP"}]}',
            }
        ]
        result = calculate_heat_source_period(records, sources)
        assert len(result) == 1
        stats = result[0]
        assert stats.heat_source_id == "vp1"
        assert stats.total_energy_kwh == pytest.approx(6.5)
        assert stats.total_cost_sek == pytest.approx(3.75)
        assert len(stats.components) == 2

        hp = next(c for c in stats.components if c.component_id == "heat_pump")
        assert hp.energy_kwh == pytest.approx(3.5)
        assert hp.cost_sek == pytest.approx(1.95)

        eh = next(c for c in stats.components if c.component_id == "electric_heater")
        assert eh.energy_kwh == pytest.approx(3.0)

    def test_percentage_calculation(self):
        """Test that percentage_of_total is calculated correctly."""
        records = [
            {
                "heat_source_id": "vp1",
                "component": "heat_pump",
                "energy_kwh": 3.0,
                "cost_sek": 1.50,
                "avg_power_w": 400.0,
            },
            {
                "heat_source_id": "vp1",
                "component": "electric_heater",
                "energy_kwh": 1.0,
                "cost_sek": 0.50,
                "avg_power_w": 1000.0,
            },
        ]
        sources = [{"id": "vp1", "name": "VP", "config": "{}"}]
        result = calculate_heat_source_period(records, sources)
        hp = next(c for c in result[0].components if c.component_id == "heat_pump")
        eh = next(c for c in result[0].components if c.component_id == "electric_heater")
        assert hp.percentage_of_total == pytest.approx(75.0)
        assert eh.percentage_of_total == pytest.approx(25.0)


class TestLoadHeatSourceConfig:
    """Tests for load_heat_source_config."""

    def test_parse_full_config(self):
        """Test parsing a complete config row."""
        row = {
            "id": "vp1",
            "name": "Frånluft",
            "energy_sensor": "sensor.energy",
            "power_sensor": "sensor.power",
            "config": '{"components": [{"id": "heat_pump", "name": "VP"}], "electric_heater_threshold_w": 800}',
        }
        cfg = load_heat_source_config(row)
        assert cfg.id == "vp1"
        assert cfg.electric_heater_threshold_w == 800.0
        assert len(cfg.components) == 1

    def test_parse_empty_config(self):
        """Test parsing with empty config uses defaults."""
        row = {
            "id": "vp1",
            "name": "Test",
            "energy_sensor": "sensor.e",
            "power_sensor": "sensor.p",
            "config": "{}",
        }
        cfg = load_heat_source_config(row)
        assert cfg.electric_heater_threshold_w == 700.0
        assert len(cfg.components) == 2  # default components

    def test_parse_invalid_json(self):
        """Test parsing with invalid JSON falls back to defaults."""
        row = {
            "id": "vp1",
            "name": "Test",
            "energy_sensor": "sensor.e",
            "power_sensor": "sensor.p",
            "config": "not json",
        }
        cfg = load_heat_source_config(row)
        assert cfg.electric_heater_threshold_w == 700.0

    def test_solar_mode_parses_flags(self):
        """Solar mode sets has_solar=True, has_compressor=False, single component."""
        import json
        row = {
            "id": "car1",
            "name": "Car charger",
            "energy_sensor": "sensor.easee_lifetime_energy",
            "power_sensor": "",
            "config": json.dumps({
                "has_compressor": False,
                "has_solar": True,
                "solar_sensor": "sensor.charge_car_sun_energy_total",
                "components": [{"id": "electric_heater", "name": "Electricity use"}],
            }),
        }
        cfg = load_heat_source_config(row)
        assert cfg.has_solar is True
        assert cfg.has_compressor is False
        assert cfg.solar_sensor == "sensor.charge_car_sun_energy_total"
        assert len(cfg.components) == 1
        assert cfg.components[0]["id"] == "electric_heater"

    def test_solar_mode_overrides_compressor_for_safety(self):
        """If both has_compressor and has_solar are true, solar wins (compressor forced off)."""
        import json
        row = {
            "id": "car1",
            "name": "Car charger",
            "energy_sensor": "sensor.e",
            "power_sensor": "",
            "config": json.dumps({
                "has_compressor": True,
                "has_solar": True,
                "solar_sensor": "sensor.solar",
            }),
        }
        cfg = load_heat_source_config(row)
        assert cfg.has_solar is True
        assert cfg.has_compressor is False


class TestCalculateHeatSourcePeriodWithSolar:
    """Tests for calculate_heat_source_period with solar-mode sources."""

    def _make_sources(self):
        import json
        return [
            {
                "id": "car1",
                "name": "Car charger",
                "config": json.dumps({
                    "has_solar": True,
                    "components": [{"id": "electric_heater", "name": "Electricity use"}],
                }),
            }
        ]

    def test_solar_aggregation_sums_solar_kwh_and_value(self):
        """Solar kWh and spot value are summed correctly across records."""
        records = [
            {
                "heat_source_id": "car1",
                "component": "electric_heater",
                "energy_kwh": 1.0,
                "cost_sek": 0.50,
                "avg_power_w": 400.0,
                "solar_energy_kwh": 0.5,
                "solar_spot_value_sek": 0.25,
            },
            {
                "heat_source_id": "car1",
                "component": "electric_heater",
                "energy_kwh": 2.0,
                "cost_sek": 1.00,
                "avg_power_w": 600.0,
                "solar_energy_kwh": 1.0,
                "solar_spot_value_sek": 0.50,
            },
        ]
        result = calculate_heat_source_period(records, self._make_sources())
        assert len(result) == 1
        s = result[0]
        assert s.has_solar is True
        assert s.solar_energy_kwh == pytest.approx(1.5)
        assert s.solar_spot_value_sek == pytest.approx(0.75)

    def test_purchased_kwh_equals_energy_minus_solar(self):
        """purchased_kwh = sum(energy_kwh), total_energy = purchased + solar."""
        records = [
            {
                "heat_source_id": "car1",
                "component": "electric_heater",
                "energy_kwh": 3.0,
                "cost_sek": 1.50,
                "avg_power_w": 500.0,
                "solar_energy_kwh": 1.0,
                "solar_spot_value_sek": 0.40,
            },
        ]
        result = calculate_heat_source_period(records, self._make_sources())
        s = result[0]
        assert s.purchased_kwh == pytest.approx(3.0)
        assert s.total_energy_kwh == pytest.approx(4.0)  # 3 purchased + 1 solar
        assert s.purchased_cost_sek == pytest.approx(1.50)

    def test_non_solar_source_has_zero_solar_fields(self):
        """Non-solar sources default to zero solar fields."""
        import json
        sources = [{"id": "vp1", "name": "VP", "config": json.dumps({"has_compressor": True})}]
        records = [
            {
                "heat_source_id": "vp1",
                "component": "heat_pump",
                "energy_kwh": 2.0,
                "cost_sek": 1.0,
                "avg_power_w": 400.0,
            }
        ]
        result = calculate_heat_source_period(records, sources)
        s = result[0]
        assert s.has_solar is False
        assert s.solar_energy_kwh == pytest.approx(0.0)
        assert s.solar_spot_value_sek == pytest.approx(0.0)
        assert s.total_energy_kwh == pytest.approx(2.0)
