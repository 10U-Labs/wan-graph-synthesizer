"""Draw the backbone's paths over the fiber the whole synthesis was chosen with.

Every backbone node owes its tenant a number of ways out that no one city's loss takes two
of, and an operator pays for every path they hold. So the synthesis owes them the paths they
asked for and nothing besides. This module produces that list of paths, and it does it in
two steps: the fiber to buy is chosen for the whole synthesis at once by
:mod:`synthesizer.survivable`, and the paths are then read off that fiber, one site at a
time, as the ways out each site actually holds over it.

Splitting it that way is the point. The four passes that stood here until GitHub issue #60
decided one pair of sites at a time -- which pairs to join, which fiber each pair's path
took, where to put a second path back, how to relieve a city carrying the whole network --
and no pass ever reconsidered what an earlier one had settled. Each decision was defensible
when it was taken, and together they left 54 of the 192 published paths buying nobody a way
out: 23,917 of the 83,927 fiber miles six tenants were paying for then, 28 per cent of it,
on paths that could all be taken out at once without costing a single site a way out
or leaving one city carrying the network. The paths came from every pass, so no one pass was
the defect; the sequence was.

What is left after the choice is ordinary reading. A site's ways out over the fiber the
synthesis bought are the fewest-mile set of paths out of it that no one city's loss takes two
of, which is what :func:`synthesizer.ceiling.independent_paths` already computes, and the
tenant's number says how many of them are drawn. A path and its reverse are the same fiber
and are drawn once. An operator's pin is honoured whatever the choice said. And a path no
site needs is dropped, because the whole complaint in issue #60 is paths nobody needs.

One thing the reading cannot give a tenant is the thing it is really buying. Two ways out of
every site is bought so that the backbone stays in one piece when a city goes dark, and a
site can hold both of its own ways out while the cities its peers depend on are the ones that
fail: three of the five tenants asking for two published a network that some one city's loss
broke in two (GitHub issue #112). So the paths are asked that question once they are read
off the fiber, and every city whose loss would split them is given one more path round it
(see :func:`_relieved`). That is a requirement over the whole network rather than a fifth
pass over pairs -- it is asked once, of the finished list, and the paths it adds are prunable
like any other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from itertools import combinations

from synthesizer.ceiling import (
    _TOLERANCE,
    _budget,
    BackupPathLimit,
    PathProofInputs,
    independent_paths,
)
from synthesizer.input_graph import FiberSegment, carriers_along, link_key
from synthesizer.graphs import (
    adjacency_by_carrier,
    articulation_points,
    build_adjacency,
    connected_components,
    dijkstra,
    path_link_keys,
    reconstruct_path,
    undirected_adjacency,
)
from synthesizer.model import LINK_FOR_PIN, LINK_FOR_TARGET, SynthesisPath
from synthesizer.survivable import FiberInputs, choose_fiber
from synthesizer.validation import diverse_path_count


def path_geometry_miles(
    path: tuple[str, ...],
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> float:
    """Sum the per-fiber-segment straight-line estimate along a path (display)."""
    return sum(
        fiber_segments[link_key(path[index], path[index + 1])].distance_miles
        for index in range(len(path) - 1)
    )


@dataclass(frozen=True)
class BackboneConstraints:
    """The operator's instructions to the mesh: their pins, their prunes, and the numbers.

    ``number_of_diverse_paths`` is how many ways out each backbone node is bought, read
    from the tenant's ``etc/*.yml``. ``forced_pairs`` are the backbone-backbone pairs the
    operator wrote in and ``removed_pairs`` the ones they struck out. ``limit`` is their
    backup path multiple, which says how far a path may run against the direct distance
    between its two ends and so which of the carrier's fiber any path may use at all.
    ``seat_cap`` is the most backbone seats their config allows, which decides whether one
    peer may take more than one of a site's ways out (see
    :func:`synthesizer.ceiling.paths_per_peer`).
    """

    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    number_of_diverse_paths: int = 3
    forced_pairs: frozenset[tuple[str, str]] = frozenset()
    limit: BackupPathLimit | None = None
    seat_cap: int | None = None


@dataclass(frozen=True)
class BackboneMesh:
    """The paths a backbone is drawn with, beside the fewest miles it could have run.

    ``lower_bound_miles`` is the answer to the linear-programming relaxation the fiber was
    chosen by (see :mod:`synthesizer.survivable`): no synthesis meeting the same requirements
    over the same fiber runs fewer miles than that. It travels with the paths because a
    synthesis is only as good as the shortest synthesis there is, and until that number is
    published nobody outside the build can say how close this one came.
    """

    paths: list[SynthesisPath]
    lower_bound_miles: float


@dataclass(frozen=True)
class _DrawnFiber:
    """The fiber a synthesis bought, beside the whole fiber it was chosen out of.

    Every site's ways out are read off ``bought`` and nothing else (see
    :func:`_ways_out_of`). ``bought_by_carrier`` is it split into what each carrier could
    sell a path over (see :func:`synthesizer.graphs.adjacency_by_carrier`), computed once
    here rather than once per site, because a site's ways out are proved one carrier at a
    time and there are as many sites as the backbone holds.

    ``whole`` is the carriers' fiber the choice was made out of, and three things still ask
    it questions: what a path costs and who would sell it (:func:`_laid`), where an
    operator's pin may run (:func:`_bought_fiber`), and what fiber goes round a city
    carrying the whole network (:func:`_path_around`). None of them is a site's ways out.

    ``distances`` is how far apart every two cities are over that whole fiber, which is what
    says which two sites a path round a city is worth buying between (see
    :func:`_pairs_across`).
    """

    backbone_ids: tuple[str, ...]
    distances: dict[str, dict[str, float]]
    bought: dict[tuple[str, str], FiberSegment]
    bought_by_carrier: dict[str, dict[str, list[tuple[str, float]]]]
    whole: dict[tuple[str, str], FiberSegment]
    constraints: BackboneConstraints


def _fiber_of(paths: list[SynthesisPath]) -> tuple[set[str], set[tuple[str, str]]]:
    """The cities a set of paths crosses and the fiber segments they run over."""
    segments: set[tuple[str, str]] = set()
    for use in paths:
        segments |= path_link_keys(use.path)
    return {city for segment in segments for city in segment}, segments


def _one_network(paths: list[SynthesisPath], backbone_ids: tuple[str, ...]) -> bool:
    """Whether the fiber these paths run over joins every backbone node into one network."""
    cities, segments = _fiber_of(paths)
    return len(connected_components(cities | set(backbone_ids), segments)) == 1


def _cut_cities(
    paths: list[SynthesisPath], backbone_ids: tuple[str, ...]
) -> set[str]:
    """The cities whose loss would split the fiber these paths run over."""
    cities, segments = _fiber_of(paths)
    return articulation_points(cities | set(backbone_ids), segments)


def _no_single_point_of_failure(
    paths: list[SynthesisPath], backbone_ids: tuple[str, ...]
) -> bool:
    """Whether no one city's loss would split the fiber these paths run over."""
    return not _cut_cities(paths, backbone_ids)


def _pinned_path(
    pair: tuple[str, str],
    by_carrier: dict[str, dict[str, list[tuple[str, float]]]],
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> SynthesisPath | None:
    """The shortest single-carrier path for one pair the operator pinned.

    A pin is an instruction rather than a proposal, so it is drawn whatever the choice of
    fiber said and its own fiber is added to the synthesis. One thing a pin cannot ask for
    is a pair no carrier can join, and nothing is drawn for such a pair -- an operator who
    pins two cities no one company reaches has asked for a path there is nobody to buy.

    The shortest way each carrier has is drawn and the shortest of those is taken, so the
    pin is honoured over the fewest fiber miles anybody can sell it in. Fiber naming no
    carrier is searched whole, which is every fixture and every caller with no merged
    carriers behind it.
    """
    near, far = pair
    maps = by_carrier or {"": build_adjacency(fiber_segments)}
    drawn: list[tuple[str, ...]] = []
    for _carrier, adjacency in sorted(maps.items()):
        _distances, predecessors = dijkstra(adjacency, near)
        path = reconstruct_path(near, far, predecessors)
        if path:
            drawn.append(path)
    if not drawn:
        return None
    path = min(drawn, key=lambda one: (path_geometry_miles(one, fiber_segments), one))
    return SynthesisPath(
        "backbone_mesh", near, far, path,
        path_geometry_miles(path, fiber_segments), LINK_FOR_PIN,
        carrier=_carrier_of(path, fiber_segments),
    )


def _carrier_of(
    path: tuple[str, ...], fiber_segments: dict[tuple[str, str], FiberSegment]
) -> str:
    """Which carrier a path is ordered from, or empty where no carrier owns any of it.

    A path built one carrier at a time has at least one carrier able to sell all of it;
    where several can, the first by name is named, so the same path published twice names
    the same company. A path running only over fiber nobody owns -- local fiber between
    two fabricated twins -- names nobody, which is the truth about it.
    """
    owners = carriers_along(path, fiber_segments)
    return min(owners) if owners else ""


def _proved_over(
    site: str,
    fiber: dict[tuple[str, str], FiberSegment],
    by_carrier: dict[str, dict[str, list[tuple[str, float]]]],
    drawn: _DrawnFiber,
) -> list[tuple[str, ...]]:
    """The ways out of ``site`` one set of fiber carries, shortest first, cut to the number.

    The fewest-mile set of paths out of the site that no one city's loss takes two of, cut
    to the number its tenant asked for. Which of them is taken makes no difference to the
    protection: the set is pairwise clear of one another by construction, so any of them is
    a way out that fails on its own, and taking the shortest ones is taking the same
    protection over less fiber.

    A peer the operator struck out is not a place a way out may end, so it is left out of
    the peers the paths are proved against rather than drawn and then discarded.
    """
    constraints = drawn.constraints
    peers = tuple(
        node
        for node in drawn.backbone_ids
        if node == site or link_key(site, node) not in constraints.removed_pairs
    )
    proof = PathProofInputs(
        peers, build_adjacency(fiber), constraints.limit,
        constraints.number_of_diverse_paths, constraints.seat_cap, by_carrier,
    )
    return sorted(
        independent_paths(site, proof),
        key=lambda path: (path_geometry_miles(path, fiber), path),
    )[: constraints.number_of_diverse_paths]


def _ways_out_of(site: str, drawn: _DrawnFiber) -> list[tuple[str, ...]]:
    """The paths ``site`` is drawn with: what it holds over the fiber the synthesis bought.

    The fiber the choice bought and nothing else. Choosing which of the carriers' segments
    to buy is the expensive step of a build and the one the whole synthesizer is arranged
    around, so a site drawn over fiber the choice never picked is a site the choice was
    made for nothing -- and that is what used to happen to 29 of the 37 backbone seats
    ``etc/`` declares, because the two halves were asking different questions (GitHub issue
    #113).

    They ask one question now. :func:`synthesizer.survivable.choose_fiber` writes every
    requirement over one carrier's own fiber, cut to the segments a path from that site to
    those peers could run on inside the operator's backup path multiple, which is what
    :func:`_proved_over` measures a finished path against. So the ways out the choice bought
    for a site are ways out the reading can find over what it bought, and there is nothing
    left to fall back to.
    """
    return _proved_over(site, drawn.bought, drawn.bought_by_carrier, drawn)


def _laid(drawn: _DrawnFiber, pinned: list[SynthesisPath]) -> list[SynthesisPath]:
    """Every distinct path the synthesis holds, each naming the sites that reached for it.

    A path and its reverse are the same fiber, so the two sites at its ends reaching for it
    is one path drawn once with both of them recorded against it. That record is what lets
    :func:`synthesizer.validation.unrequested_mesh_links` tell a site's own path from one it
    is holding because a peer needed it, which is the whole of what an operator reading a
    network larger than the one they asked for is owed.
    """
    laid: dict[tuple[str, ...], SynthesisPath] = {
        min(use.path, use.path[::-1]): use for use in pinned
    }
    for site in sorted(drawn.backbone_ids):
        for path in _ways_out_of(site, drawn):
            key = min(path, path[::-1])
            held = laid.get(key)
            if held is None:
                laid[key] = SynthesisPath(
                    "backbone_mesh", path[0], path[-1], path,
                    path_geometry_miles(path, drawn.whole), LINK_FOR_TARGET, (site,),
                    _carrier_of(path, drawn.whole),
                )
            elif held.reason == LINK_FOR_TARGET and site not in held.requested_by:
                laid[key] = replace(
                    held, requested_by=tuple(sorted((*held.requested_by, site)))
                )
    return [laid[key] for key in sorted(laid)]


def _pairs_across(
    city: str, paths: list[SynthesisPath], drawn: _DrawnFiber
) -> list[tuple[str, str]]:
    """The backbone pairs ``city``'s loss would separate, the nearest pair first.

    Losing a city leaves the drawn paths in pieces, and a pair of backbone nodes with one
    end in each of two of those pieces is a pair that could be joined round the city
    instead. Only the pieces the city itself holds apart are offered: two nodes the paths
    never joined at all are two nodes this city's loss costs nothing, and a path between
    them would leave every city it crossed carrying a network that was already in two.

    Nearest first by how far apart the two ends are over the carriers' whole fiber, so the
    way round a city is looked for where it is shortest and the same fiber gives the same
    answer every time.
    """
    cities, segments = _fiber_of(paths)
    places = cities | set(drawn.backbone_ids)
    apart = {
        place: index
        for index, piece in enumerate(connected_components(places - {city}, segments))
        for place in piece
    }
    sides: dict[int, list[str]] = {}
    for site in sorted(set(drawn.backbone_ids) - {city}):
        sides.setdefault(apart[site], []).append(site)
    split = sorted({apart[near] for near in undirected_adjacency(places, segments)[city]})
    pairs = [
        (near, far)
        for left, right in combinations(split, 2)
        for near in sides.get(left, [])
        for far in sides.get(right, [])
    ]
    return sorted(
        pairs,
        key=lambda ends: (drawn.distances.get(ends[0], {}).get(ends[1], math.inf), ends),
    )


def _path_around(
    city: str, paths: list[SynthesisPath], drawn: _DrawnFiber
) -> SynthesisPath | None:
    """One more path joining two backbone nodes ``city``'s loss would otherwise separate.

    The shortest way one carrier has between the two, over the carriers' whole fiber with
    the city taken out of it. It is drawn the way an operator's pin is drawn (see
    :func:`_pinned_path`) because it is the same question -- the fewest fiber miles anybody
    can sell between two named sites -- and the pairs are tried nearest first, so the first
    one somebody can sell is the one taken.

    A path running further than the operator's backup path multiple allows is refused
    rather than drawn: a path past that bound is one nobody would order. ``None`` where no
    pair can be joined at all, which says the carriers' fiber offers no way round this city.
    """
    fiber = {
        segment: link for segment, link in drawn.whole.items() if city not in segment
    }
    by_carrier = adjacency_by_carrier(fiber)
    limit = drawn.constraints.limit
    for near, far in _pairs_across(city, paths, drawn):
        found = _pinned_path((near, far), by_carrier, fiber)
        if found is None:
            continue
        if limit is not None and (
            found.distance_miles > _budget(near, far, limit) + _TOLERANCE
        ):
            continue
        return replace(found, reason=LINK_FOR_TARGET)
    return None


def _relieved(paths: list[SynthesisPath], drawn: _DrawnFiber) -> list[SynthesisPath]:
    """The paths as laid, with one more added for every city whose loss would split them.

    A tenant buying two ways out of every backbone node is buying a backbone that stays in
    one piece when a city goes dark, and reading each site's ways out on its own does not
    deliver it: three of the five tenants asking for two published a network that some one
    city's loss broke in two, and the loss of Atlanta, GA left Ashburn, VA and New York, NY
    with no way to DAF's other nine backbone nodes (GitHub issue #112). So the finished list
    of paths is asked which cities its fiber cannot survive losing, and each of them in turn
    is given a path round it (see :func:`_path_around`). The city taken first is the first
    in sorted order, so the same fiber gives the same answer every time.

    A city the carriers' fiber offers no way round stays a single point of failure, and the
    next city is taken instead. That shortfall is
    ``backbone_mesh_survives_any_one_site_loss``'s to report, and what it reports then is
    true of the carriers' fiber rather than only of this synthesis -- which is worth more
    than fiber on the map nobody would buy. Minuteman is the live case: Minot, ND can be
    sold one way out and no more, so its 606-mile path to Cheyenne, WY is the only way it is
    reached and Max, ND, Bismarck, ND, Dickinson, ND and Cheyenne, WY each split the network
    when they go dark. There is no second path to draw and nobody to order it from.

    A tenant asking for one way out of each node is asked for nothing here. One way out is
    one way out, and a network built to it comes apart wherever its fiber does: Yurop asks
    for one, four cities split its published network, and that is the honest answer to what
    it bought rather than a defect to spend its money on.

    This is a requirement of the whole network and not the pair-at-a-time repair GitHub
    issue #60 retired. It runs once, over the finished list of paths, and what it adds is
    ordinary fiber the prune may take back out again (see :func:`_needed`).

    It ends because every path added joins two pieces one city held apart, so that city
    separates one piece fewer than it did, and every city the new path crosses now lies on a
    cycle with it -- a city whose loss splits nothing. No city becomes a cut city that was
    not one already, so each pass either takes one off the list or writes one off.
    """
    relieved = list(paths)
    if drawn.constraints.number_of_diverse_paths < 2:
        return relieved
    beyond_help: set[str] = set()
    while True:
        cut = sorted(_cut_cities(relieved, drawn.backbone_ids) - beyond_help)
        if not cut:
            return relieved
        added = _path_around(cut[0], relieved, drawn)
        if added is None:
            beyond_help.add(cut[0])
            continue
        relieved.append(added)


def _needed(
    paths: list[SynthesisPath], backbone_ids: tuple[str, ...], target: int
) -> list[SynthesisPath]:
    """The paths left once every path nobody needs has been taken out, longest first.

    A path earns the fiber it runs on when taking it out would cost some backbone node a
    way out its tenant asked for, break the backbone into pieces, or leave a city whose
    loss splits the fiber where none stood before. A path that costs none of those three is
    a path an operator pays for every month and gets nothing for, which is the 54 paths and
    23,917 miles GitHub issue #60 is about.

    Longest first, so where two paths are interchangeable the fiber that goes is the fiber
    that costs the most miles. An operator's pin is never taken out: it is the one path
    nobody has to justify.
    """
    kept = list(paths)
    held = {site: min(target, diverse_path_count(kept, site)) for site in backbone_ids}
    intact = _no_single_point_of_failure(kept, backbone_ids)
    for spare in sorted(paths, key=lambda use: (-use.distance_miles, use.path)):
        if spare.reason == LINK_FOR_PIN:
            continue
        left = [use for use in kept if use is not spare]
        if any(
            min(target, diverse_path_count(left, site)) < held[site] for site in backbone_ids
        ):
            continue
        if not _one_network(left, backbone_ids):
            continue
        if intact and not _no_single_point_of_failure(left, backbone_ids):
            continue
        kept = left
    return kept


def _bought_fiber(
    backbone_ids: tuple[str, ...],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    all_distances: dict[str, dict[str, float]],
    constraints: BackboneConstraints,
    by_carrier: dict[str, dict[str, list[tuple[str, float]]]],
) -> tuple[frozenset[tuple[str, str]], float, list[SynthesisPath]]:
    """The fiber the synthesis buys, the floor under it, and the paths the operator pinned.

    The pins are drawn over the whole of the carriers' fiber rather than over what the choice
    bought, and their own segments join what was bought. An operator who writes a pair into
    ``etc/*.yml`` has decided that pair is joined, and a choice made to answer everybody
    else's requirements has no standing to overrule it.

    ``by_carrier`` goes to the choice as well as to the pins. A path is bought from one
    carrier end to end, so what a site is owed is what one carrier can sell it, and the
    choice needs the split to know that (see :func:`synthesizer.survivable._capped`).
    """
    choice = choose_fiber(FiberInputs(
        backbone_ids, fiber_segments, all_distances,
        constraints.number_of_diverse_paths, constraints.seat_cap, constraints.limit,
        by_carrier,
    ))
    drawn = (
        _pinned_path(pair, by_carrier, fiber_segments)
        for pair in sorted(constraints.forced_pairs)
    )
    pinned = [use for use in drawn if use is not None]
    segments = set(choice.segments)
    for use in pinned:
        segments |= path_link_keys(use.path)
    return frozenset(segments), choice.lower_bound_miles, pinned


def backbone_mesh(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> BackboneMesh:
    """Draw the backbone-to-backbone paths, and say how few miles they could have run in.

    The fiber comes first and comes whole: :func:`synthesizer.survivable.choose_fiber`
    picks the fewest-mile set of the carrier's segments in which every backbone node holds
    the ways out its tenant asked for and every pair of them is joined as many times over.
    Nothing about that choice is taken one pair at a time, so nothing later in the build can
    spoil a decision taken earlier in it.

    The paths are then read off that fiber, one site at a time (see :func:`_ways_out_of`),
    every city whose loss would split them is given a path round it (see :func:`_relieved`),
    and every path no site needs is taken back out (see :func:`_needed`). What is published
    is what is left, which is why a published network now holds no path an outside reader
    can remove without costing somebody something -- the property
    ``test_published_syntheses.removable_paths`` measures against the five live maps.

    A backbone the carrier's fiber says nothing about draws nothing, and a node it says
    nothing about is left out while the rest are drawn. The shortfall is
    :func:`synthesizer.validation.backbone_mesh_independence_deficient`'s to report.
    """
    whole_by_carrier = adjacency_by_carrier(fiber_segments)
    segments, floor, pinned = _bought_fiber(
        backbone_ids, fiber_segments, all_distances, constraints, whole_by_carrier
    )
    bought = {segment: fiber_segments[segment] for segment in sorted(segments)}
    drawn = _DrawnFiber(
        backbone_ids, all_distances, bought, adjacency_by_carrier(bought),
        fiber_segments, constraints,
    )
    laid = _relieved(_laid(drawn, pinned), drawn)
    return BackboneMesh(
        _needed(laid, backbone_ids, constraints.number_of_diverse_paths), floor
    )
