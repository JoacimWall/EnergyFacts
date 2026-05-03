"""Heat source energy calculation engine for EnergyFacts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from .const import DEFAULT_ELPATRON_THRESHOLD_W

_LOGGER = logging.getLogger(__name__)


@dataclass
class HeatSourceConfig:
    """Configuration for a heat source."""

    id: str
    name: str
    energy_sensor: str
    power_sensor: str = ""  # Optional — kept for backwards compatibility
    has_compressor: bool = True
    has_solar: bool = False
    solar_sensor: str = ""
    components: list[dict] = field(default_factory=list)
    electric_heater_threshold_w: float = DEFAULT_ELPATRON_THRESHOLD_W


@dataclass
class ComponentEnergySplit:
    """Result of splitting energy between components."""

    component: str
    energy_kwh: float
    power_w: float


@dataclass
class ComponentPeriodStats:
    """Aggregated stats for a single component over a period."""

    component_id: str
    component_name: str
    energy_kwh: float
    cost_sek: float
    avg_power_w: float
    percentage_of_total: float


@dataclass
class HeatSourcePeriodStats:
    """Aggregated stats for a heat source over a period."""

    heat_source_id: str
    heat_source_name: str
    components: list[ComponentPeriodStats]
    total_energy_kwh: float
    total_cost_sek: float
    has_solar: bool = False
    solar_energy_kwh: float = 0.0
    solar_cost_sek: float = 0.0
    purchased_kwh: float = 0.0
    purchased_cost_sek: float = 0.0


def split_energy_by_power(
    total_power_w: float,
    energy_delta_kwh: float,
    config: HeatSourceConfig,
) -> list[ComponentEnergySplit]:
    """Split energy between heat pump and electric heater based on power threshold.

    If total power < threshold: 100% goes to heat_pump.
    If total power >= threshold: heat_pump gets (threshold/total_power) share,
    electric_heater gets the rest.
    """
    if not config.has_compressor:
        return [
            ComponentEnergySplit(
                component="electric_heater",
                energy_kwh=max(energy_delta_kwh, 0),
                power_w=max(total_power_w, 0),
            ),
        ]

    if total_power_w <= 0 or energy_delta_kwh <= 0:
        return [
            ComponentEnergySplit(component="heat_pump", energy_kwh=0, power_w=0),
            ComponentEnergySplit(component="electric_heater", energy_kwh=0, power_w=0),
        ]

    threshold = config.electric_heater_threshold_w

    if total_power_w < threshold:
        return [
            ComponentEnergySplit(
                component="heat_pump",
                energy_kwh=energy_delta_kwh,
                power_w=total_power_w,
            ),
            ComponentEnergySplit(
                component="electric_heater",
                energy_kwh=0,
                power_w=0,
            ),
        ]

    heat_pump_ratio = threshold / total_power_w
    heat_pump_energy = energy_delta_kwh * heat_pump_ratio
    heater_energy = energy_delta_kwh - heat_pump_energy
    heat_pump_power = threshold
    heater_power = total_power_w - threshold

    return [
        ComponentEnergySplit(
            component="heat_pump",
            energy_kwh=heat_pump_energy,
            power_w=heat_pump_power,
        ),
        ComponentEnergySplit(
            component="electric_heater",
            energy_kwh=heater_energy,
            power_w=heater_power,
        ),
    ]


def calculate_heat_source_period(
    records: list[dict],
    heat_sources: list[dict],
) -> list[HeatSourcePeriodStats]:
    """Aggregate heat source energy records into period stats.

    records: list of heat_source_energy rows from the database.
    heat_sources: list of heat_source config rows from the database.
    """
    source_map = {hs["id"]: hs for hs in heat_sources}

    # Group by heat_source_id → component
    by_source: dict[str, dict[str, dict]] = {}
    for rec in records:
        hs_id = rec["heat_source_id"]
        comp = rec["component"]
        if hs_id not in by_source:
            by_source[hs_id] = {}
        if comp not in by_source[hs_id]:
            by_source[hs_id][comp] = {
                "energy_kwh": 0,
                "cost_sek": 0,
                "power_sum": 0,
                "count": 0,
            }
        agg = by_source[hs_id][comp]
        agg["energy_kwh"] += rec.get("energy_kwh", 0)
        agg["cost_sek"] += rec.get("cost_sek", 0)
        agg["power_sum"] += rec.get("avg_power_w", 0)
        agg["count"] += 1

    results = []
    for hs_id, comp_data in by_source.items():
        hs_info = source_map.get(hs_id, {})
        hs_name = hs_info.get("name", hs_id)
        config_json = hs_info.get("config", "{}")
        try:
            config_parsed = json.loads(config_json) if isinstance(config_json, str) else config_json
        except (json.JSONDecodeError, TypeError):
            config_parsed = {}
        has_solar = config_parsed.get("has_solar", False)
        comp_names = {
            c["id"]: c["name"]
            for c in config_parsed.get("components", [])
        }

        if has_solar:
            solar_agg = comp_data.get("solar", {})
            total_solar_kwh = solar_agg.get("energy_kwh", 0.0)
            total_solar_cost = solar_agg.get("cost_sek", 0.0)
            purchased_kwh = sum(c["energy_kwh"] for cid, c in comp_data.items() if cid != "solar")
            purchased_cost = sum(c["cost_sek"] for cid, c in comp_data.items() if cid != "solar")
        else:
            total_solar_kwh = 0.0
            total_solar_cost = 0.0
            purchased_kwh = sum(c["energy_kwh"] for c in comp_data.values())
            purchased_cost = sum(c["cost_sek"] for c in comp_data.values())

        total_cost = sum(c["cost_sek"] for c in comp_data.values())
        total_energy = purchased_kwh + total_solar_kwh

        components = []
        for comp_id, agg in comp_data.items():
            pct = (agg["energy_kwh"] / total_energy * 100) if total_energy > 0 else 0
            avg_pw = agg["power_sum"] / agg["count"] if agg["count"] > 0 else 0
            components.append(ComponentPeriodStats(
                component_id=comp_id,
                component_name=comp_names.get(comp_id, comp_id),
                energy_kwh=agg["energy_kwh"],
                cost_sek=agg["cost_sek"],
                avg_power_w=avg_pw,
                percentage_of_total=pct,
            ))

        results.append(HeatSourcePeriodStats(
            heat_source_id=hs_id,
            heat_source_name=hs_name,
            components=components,
            total_energy_kwh=total_energy,
            total_cost_sek=total_cost,
            has_solar=has_solar,
            solar_energy_kwh=total_solar_kwh,
            solar_cost_sek=total_solar_cost,
            purchased_kwh=purchased_kwh,
            purchased_cost_sek=purchased_cost,
        ))

    return results


def load_heat_source_config(db_row: dict) -> HeatSourceConfig:
    """Parse a database row into a HeatSourceConfig."""
    config_str = db_row.get("config", "{}")
    try:
        config_data = json.loads(config_str) if isinstance(config_str, str) else config_str
    except (json.JSONDecodeError, TypeError):
        config_data = {}

    has_solar = config_data.get("has_solar", False)
    # has_solar and has_compressor are mutually exclusive; solar wins
    has_compressor = config_data.get("has_compressor", True) and not has_solar

    if has_solar:
        default_components = [
            {"id": "solar", "name": "Solar energy"},
            {"id": "electric_heater", "name": "Electricity use"},
        ]
    elif has_compressor:
        default_components = [
            {"id": "heat_pump", "name": "Kompressorvärme"},
            {"id": "electric_heater", "name": "Immersion heater"},
        ]
    else:
        default_components = [
            {"id": "electric_heater", "name": "Electricity use"},
        ]

    return HeatSourceConfig(
        id=db_row["id"],
        name=db_row["name"],
        energy_sensor=db_row["energy_sensor"],
        power_sensor=db_row.get("power_sensor", ""),
        has_compressor=has_compressor,
        has_solar=has_solar,
        solar_sensor=config_data.get("solar_sensor", ""),
        components=config_data.get("components", default_components),
        electric_heater_threshold_w=config_data.get(
            "electric_heater_threshold_w", DEFAULT_ELPATRON_THRESHOLD_W
        ) if has_compressor else 0,
    )
