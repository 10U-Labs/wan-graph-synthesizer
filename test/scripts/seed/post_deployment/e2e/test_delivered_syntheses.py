from __future__ import annotations

import csv
from collections.abc import Callable
from typing import Any

import seed
from test_published_syntheses import (
    FIBER,
    backbone_groups,
    cut_cities,
    detoured_links,
    ordered_fiber_miles,
    overbuilt_pairs,
    overrun_links,
    removable_paths,
    sellable_ways_out,
    worst_haul,
)


_ROUNDED_TO = 0.001


def _rounding_slack(synthesis: dict[str, Any]) -> float:
    segments = sum(1 for link in synthesis["paths"] if link["link_kind"] == FIBER)
    return (segments + 1) * _ROUNDED_TO / 2


def _tenants_outside(
    delivered_syntheses: list[dict[str, Any]],
    allowed: Callable[[float, float, float], bool],
) -> dict[str, tuple[float, float]]:
    measured = {
        synthesis["tenant"]: (
            ordered_fiber_miles(synthesis),
            synthesis["lower_bound_miles"],
            _rounding_slack(synthesis),
        )
        for synthesis in delivered_syntheses
        if synthesis["lower_bound_miles"] is not None
    }
    return {
        tenant: (miles, floor)
        for tenant, (miles, floor, slack) in measured.items()
        if not allowed(miles, floor, slack)
    }


def _paths_clear_of_a_capped_seat(synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    capped = {
        entry["id"]
        for entry in synthesis["status"]["diverse_paths"]["ceilings"]
        if entry["ceiling"] < 2
    }
    return [
        link
        for link in synthesis["links"]
        if link["source_id"] not in capped and link["target_id"] not in capped
    ]


def _published_cities(synthesis: dict[str, Any]) -> set[str]:
    return {node["name"] for node in synthesis["backbone"]}


def test_every_tenant_the_roster_declares_has_a_published_network(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    unfinished = {
        synthesis["tenant"]: synthesis["status"].get("status")
        for synthesis in delivered_syntheses
        if synthesis["status"].get("status") != "success"
    }
    assert unfinished == {}


def test_every_published_network_is_one_network(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    split = {
        synthesis["tenant"]: groups
        for synthesis in delivered_syntheses
        if len(groups := backbone_groups(synthesis)) > 1
    }
    assert split == {}


def test_every_published_network_reports_the_coverage_it_delivered(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    silent = [
        synthesis["tenant"]
        for synthesis in delivered_syntheses
        if "coverage" not in synthesis["status"]
    ]
    assert silent == []


def test_every_report_is_measured_against_the_target_its_tenant_declares(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    reported = {
        synthesis["tenant"]: synthesis["status"]["coverage"]["target_miles"]
        for synthesis in delivered_syntheses
    }
    declared = {synthesis["tenant"]: synthesis["target_miles"] for synthesis in delivered_syntheses}
    assert reported == declared


def test_every_city_a_tenant_pins_is_seated_in_its_published_backbone(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    unseated = {
        synthesis["tenant"]: sorted(set(synthesis["forced"]) - _published_cities(synthesis))
        for synthesis in delivered_syntheses
        if not set(synthesis["forced"]) <= _published_cities(synthesis)
    }
    assert unseated == {}


def test_the_reported_worst_haul_is_the_one_the_published_network_delivers(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    mismeasured = [
        (synthesis["tenant"], worst_haul(synthesis))
        for synthesis in delivered_syntheses
        if worst_haul(synthesis) != synthesis["status"]["coverage"]["worst_haul_miles"]
    ]
    assert mismeasured == []


def test_no_synthesis_stopped_short_of_its_target_with_a_seat_left_to_spend(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    gave_up_early = [
        (synthesis["tenant"], len(synthesis["backbone"]), synthesis["seat_cap"])
        for synthesis in delivered_syntheses
        if not synthesis["status"]["coverage"]["met"]
        and len(synthesis["backbone"]) < synthesis["seat_cap"]
    ]
    assert gave_up_early == []


def test_no_published_link_runs_further_than_its_tenant_allows(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    overrun = {
        synthesis["tenant"]: overrun_links(synthesis)
        for synthesis in delivered_syntheses
        if overrun_links(synthesis)
    }
    assert overrun == {}


def test_no_published_link_wanders_past_the_fiber_its_own_network_carries(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    wandering = {
        synthesis["tenant"]: detoured_links(synthesis)
        for synthesis in delivered_syntheses
        if detoured_links(synthesis)
    }
    assert wandering == {}


def test_no_published_network_leaves_a_site_short_of_the_links_it_was_asked_for(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    short = {
        synthesis["tenant"]: synthesis["status"]["diverse_paths"]["short"]
        for synthesis in delivered_syntheses
    }
    assert {tenant: sites for tenant, sites in short.items() if sites} == {}


def test_no_published_network_draws_a_pair_more_paths_than_its_tenant_asked_for(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    overbuilt = {
        synthesis["tenant"]: overbuilt_pairs(synthesis)
        for synthesis in delivered_syntheses
        if overbuilt_pairs(synthesis)
    }
    assert overbuilt == {}


def test_no_published_network_holds_a_path_that_buys_nobody_a_diverse_path(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    spare = {synthesis["tenant"]: removable_paths(synthesis) for synthesis in delivered_syntheses}
    assert {tenant: paths for tenant, paths in spare.items() if paths} == {}


def test_no_published_network_is_split_by_the_loss_of_one_city(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    split = {
        synthesis["tenant"]: cut_cities(_paths_clear_of_a_capped_seat(synthesis))
        for synthesis in delivered_syntheses
        if synthesis["number_of_diverse_paths"] >= 2
    }
    assert {tenant: cities for tenant, cities in split.items() if cities} == {}


def test_no_published_network_runs_more_than_twice_the_fewest_miles_it_could_have(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    assert _tenants_outside(
        delivered_syntheses, lambda miles, floor, _slack: miles <= 2 * floor
    ) == {}


def test_no_published_network_runs_more_than_a_tenth_further_than_the_floor_it_publishes(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    assert _tenants_outside(
        delivered_syntheses, lambda miles, floor, _slack: miles <= 1.1 * floor
    ) == {}


def test_no_published_network_runs_fewer_miles_than_the_floor_it_publishes(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    assert _tenants_outside(
        delivered_syntheses, lambda miles, floor, slack: miles >= floor - slack
    ) == {}


def _city_names() -> dict[tuple[str, str], str]:
    named: dict[tuple[str, str], str] = {}
    for path in sorted((seed.DATA / "pops").glob("*.csv")):
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                region = (
                    row["State"] if row["Country"] == "United States" else row["Country"]
                )
                named[(row["Municipality"], row["State"])] = (
                    f"{row['Municipality']}, {region}"
                )
    return named


def _fiber_by_carrier() -> dict[str, set[frozenset[str]]]:
    named = _city_names()
    held: dict[str, set[frozenset[str]]] = {}
    for path in sorted(seed.FIBER_SEGMENTS.glob("*/*.csv")):
        pairs: set[frozenset[str]] = set()
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                near = named.get((row["A_Municipality"], row["A_State"]))
                far = named.get((row["Z_Municipality"], row["Z_State"]))
                if near and far:
                    pairs.add(frozenset({near, far}))
        held.setdefault(path.stem, set()).update(pairs)
    return held


def _anybodys_fiber(held: dict[str, set[frozenset[str]]]) -> set[frozenset[str]]:
    everyone: set[frozenset[str]] = set()
    for pairs in held.values():
        everyone |= pairs
    return everyone


def _hops(link: dict[str, Any]) -> list[frozenset[str]]:
    cities = link.get("path") or []
    return [frozenset({left, right}) for left, right in zip(cities, cities[1:])]


def _paths_changing_hands(syntheses: list[dict[str, Any]]) -> dict[str, list[str]]:
    held = _fiber_by_carrier()
    anybody = _anybodys_fiber(held)
    found: dict[str, list[str]] = {}
    for synthesis in syntheses:
        for link in synthesis["links"]:
            mine = held.get(link.get("carrier", ""), set())
            if any(hop in anybody and hop not in mine for hop in _hops(link)):
                found.setdefault(synthesis["tenant"], []).append(
                    f"{link['source_name']} to {link['target_name']}"
                )
    return found


def _paths_naming_no_carrier(syntheses: list[dict[str, Any]]) -> dict[str, list[str]]:
    anybody = _anybodys_fiber(_fiber_by_carrier())
    found: dict[str, list[str]] = {}
    for synthesis in syntheses:
        for link in synthesis["links"]:
            if not link.get("carrier") and any(hop in anybody for hop in _hops(link)):
                found.setdefault(synthesis["tenant"], []).append(
                    f"{link['source_name']} to {link['target_name']}"
                )
    return found


def test_no_published_path_changes_carrier_partway_along_itself(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    assert not _paths_changing_hands(delivered_syntheses)


def test_every_published_path_over_a_carriers_fiber_names_that_carrier(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    assert not _paths_naming_no_carrier(delivered_syntheses)


def _tenants_fiber(synthesis: dict[str, Any]) -> dict[str, set[frozenset[str]]]:
    held = _fiber_by_carrier()
    anybody = _anybodys_fiber(held)
    laid = {
        hop for link in synthesis["links"] for hop in _hops(link) if hop not in anybody
    }
    return {carrier: pairs | laid for carrier, pairs in held.items()}


def _cities_with_fiber(held: dict[str, set[frozenset[str]]]) -> set[str]:
    return {city for pair in _anybodys_fiber(held) for city in pair}


def _paths_one_peer_may_end(synthesis: dict[str, Any]) -> int:
    peers = synthesis["seat_cap"] - 1
    asked = synthesis["number_of_diverse_paths"]
    return max(1, -(-asked // peers)) if peers > 0 else 1


def _overstated_ceilings(syntheses: list[dict[str, Any]]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for synthesis in syntheses:
        held = _tenants_fiber(synthesis)
        reached = _cities_with_fiber(held)
        cities = _published_cities(synthesis)
        per_peer = _paths_one_peer_may_end(synthesis)
        for entry in synthesis["status"].get("diverse_paths", {}).get("ceilings", []):
            city = str(entry["name"])
            if city not in reached:
                continue
            sellable = sellable_ways_out(
                held, city, frozenset(cities - {city}), per_peer
            )
            if int(entry["ceiling"]) > sellable:
                found.setdefault(synthesis["tenant"], []).append(
                    f"{city} at {entry['ceiling']} against {sellable}"
                )
    return found


def test_no_published_networks_ceiling_is_higher_than_the_paths_its_carriers_can_sell(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    assert not _overstated_ceilings(delivered_syntheses)


def _submarine_pairs(synthesis: dict[str, Any]) -> set[frozenset[str]]:
    return {
        frozenset({link["source_name"], link["target_name"]})
        for link in synthesis["paths"]
        if link["link_kind"] == FIBER and link["submarine"]
    }


def _runs_under_water(path: list[str], under_water: set[frozenset[str]]) -> bool:
    return any(
        frozenset({near, far}) in under_water for near, far in zip(path, path[1:])
    )


def _paths_each_site_holds(synthesis: dict[str, Any]) -> dict[str, list[list[str]]]:
    held: dict[str, list[list[str]]] = {}
    for link in synthesis["links"]:
        for end in (link["path"][0], link["path"][-1]):
            held.setdefault(end, []).append(link["path"])
    return held


def _sites_ashore_holding_a_crossing(synthesis: dict[str, Any]) -> list[tuple[str, ...]]:
    under_water = _submarine_pairs(synthesis)
    return [
        (synthesis["tenant"], site, " -> ".join(path))
        for site, paths in sorted(_paths_each_site_holds(synthesis).items())
        for path in paths
        if _runs_under_water(path, under_water)
        and any(not _runs_under_water(other, under_water) for other in paths)
    ]


def test_no_published_site_with_a_path_over_land_is_drawn_one_under_water(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    assert [
        offender
        for synthesis in delivered_syntheses
        for offender in _sites_ashore_holding_a_crossing(synthesis)
    ] == []
