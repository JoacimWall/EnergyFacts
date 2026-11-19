from __future__ import annotations

from types import SimpleNamespace

from custom_components.energy_facts.financial_engine import CalcParams
from custom_components.energy_facts.websocket_api import _calc_breakdown

from .test_database import db_instance  # noqa: F401  (fixture)


def test_breakdown_other_is_house_minus_measured(db_instance):  # noqa: F811
    db = db_instance
    db.upsert_hourly_record(
        "2026-03-01T10:00:00",
        {"purchased": 3.0, "production_own_use": 1.0, "unit_price_buy": 1.0, "synced": True},
    )
    db.upsert_heat_source("hp", "Heat pump", "power_threshold", "sensor.hp", "")
    db.upsert_heat_source_energy("2026-03-01T10:00:00", "hp", "compressor", 2.5, 5.0, 2500, 1.0, 1)

    params = CalcParams(transfer_fee=0.3, energy_tax=0.5, grid_compensation=0.1)
    coord = SimpleNamespace(storage=db, _calc_params=params, _yearly_params={})
    r = _calc_breakdown(coord, "2026-03-01T00:00:00", "2026-04-01T00:00:00")

    assert r["house_energy_kwh"] == 4.0
    # 3 kWh bought * (1 + 0.3 + 0.5) + 1 kWh solar * (1 + 0.1)
    assert r["house_cost_sek"] == 6.5
    assert r["other_energy_kwh"] == 1.5
    assert r["other_cost_sek"] == 1.5
