from __future__ import annotations

from types import SimpleNamespace

from custom_components.energy_facts.financial_engine import CalcParams
from custom_components.energy_facts.websocket_api import _calc_breakdown

from .test_database import db_instance  # noqa: F401  (fixture)


def test_breakdown_other_is_house_minus_measured(db_instance):  # noqa: F811
    db = db_instance
    db.upsert_hourly_record(
        "2026-03-01T10:00:00",
        {"purchased": 3.0, "production_own_use": 1.0, "unit_price_buy": 1.0,
         "unit_price_sold": 0.8, "synced": True},
    )
    db.upsert_heat_source("hp", "Heat pump", "power_threshold", "sensor.hp", "")
    db.upsert_heat_source_energy("2026-03-01T10:00:00", "hp", "compressor", 2.5, 5.0, 2500, 1.0, 1)

    params = CalcParams(transfer_fee=0.3, energy_tax=0.5, grid_compensation=0.1, tax_reduction=0.6)
    coord = SimpleNamespace(storage=db, _calc_params=params, _yearly_params={})
    r = _calc_breakdown(coord, "2026-03-01T00:00:00", "2026-04-01T00:00:00")

    assert r["house_energy_kwh"] == 4.0
    # 3 kWh bought * (1 + 0.3 + 0.5) + 1 kWh solar * (1 + 0.1)
    assert r["house_cost_sek"] == 6.5
    assert r["other_energy_kwh"] == 1.5
    # Hour's blended price 6.5 / 4 = 1.625 kWh shared by every load
    assert r["heat_sources"][0]["total_cost_sek"] == 4.06
    assert r["other_cost_sek"] == 2.44
    # Own solar: would have cost 1 * (1 + 0.3 + 0.5) to buy; sold it would earn 0.8 + 0.1
    # (no skattereduktion in 2026)
    assert r["own_use_avoided_sek"] == 1.8
    assert r["own_use_alt_income_sek"] == 0.9
    assert r["purchased_cost_sek"] == 5.4


def test_breakdown_solar_sensor_source_keeps_its_split(db_instance):  # noqa: F811
    db = db_instance
    db.upsert_hourly_record(
        "2026-06-01T12:00:00",
        {"purchased": 2.0, "production_own_use": 4.0, "unit_price_buy": 1.0,
         "unit_price_sold": 0.8, "synced": True},
    )
    db.upsert_heat_source("ev", "EV", "power_threshold", "sensor.ev", "", config='{"has_solar": true}')
    db.upsert_heat_source("hp", "Heat pump", "power_threshold", "sensor.hp", "")
    ts = "2026-06-01T12:00:00"
    db.upsert_heat_source_energy(ts, "ev", "solar", 3.0, 3.3, 3000, 1.0, 1)
    db.upsert_heat_source_energy(ts, "ev", "electric_heater", 1.0, 1.8, 3000, 1.0, 1)
    db.upsert_heat_source_energy(ts, "hp", "compressor", 1.0, 1.8, 1000, 1.0, 1)

    params = CalcParams(transfer_fee=0.3, energy_tax=0.5, grid_compensation=0.1, tax_reduction=0.6)
    coord = SimpleNamespace(storage=db, _calc_params=params, _yearly_params={})
    r = _calc_breakdown(coord, "2026-06-01T00:00:00", "2026-07-01T00:00:00")

    costs = {s["heat_source_id"]: s["total_cost_sek"] for s in r["heat_sources"]}
    assert costs["ev"] == 5.1  # measured split untouched
    # Pool left: 1 kWh bought (1.8) + 1 kWh solar (1.1) -> 1.45/kWh
    assert costs["hp"] == 1.45
    # house 2*1.8 + 4*1.1 = 8.0; other = 8.0 - 5.1 - 1.45
    assert r["other_cost_sek"] == 1.45
