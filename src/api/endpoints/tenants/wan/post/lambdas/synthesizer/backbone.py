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
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from synthesizer.ceiling import (
    BackupPathLimit,
    PathProofInputs,
    independent_paths,
    paths_per_peer,
)
from synthesizer.input_graph import FiberSegment, link_key
from synthesizer.graphs import (
    articulation_points,
    build_adjacency,
    connected_components,
    dijkstra,
    path_link_keys,
    reconstruct_path,
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
    """The fiber a synthesis bought, beside the carrier fiber it was chosen out of.

    Both are here because a site's ways out are read off the bought fiber and held against
    what the carrier's whole fiber could have given it (see :func:`_ways_out_of`).
    """

    backbone_ids: tuple[str, ...]
    bought: dict[tuple[str, str], FiberSegment]
    carrier: dict[tuple[str, str], FiberSegment]
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


def _no_single_point_of_failure(
    paths: list[SynthesisPath], backbone_ids: tuple[str, ...]
) -> bool:
    """Whether no one city's loss would split the fiber these paths run over."""
    cities, segments = _fiber_of(paths)
    return not articulation_points(cities | set(backbone_ids), segments)


def _pinned_path(
    pair: tuple[str, str],
    adjacency: dict[str, list[tuple[str, float]]],
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> SynthesisPath | None:
    """The shortest path over the carrier's fiber for one pair the operator pinned.

    A pin is an instruction rather than a proposal, so it is drawn whatever the choice of
    fiber said and its own fiber is added to the synthesis. A pair the carrier's fiber cannot
    join at all is the one thing a pin cannot ask for, and nothing is drawn for it.
    """
    near, far = pair
    _distances, predecessors = dijkstra(adjacency, near)
    path = reconstruct_path(near, far, predecessors)
    if not path:
        return None
    return SynthesisPath(
        "backbone_mesh", near, far, path,
        path_geometry_miles(path, fiber_segments), LINK_FOR_PIN,
    )


def _proved_over(
    site: str, fiber: dict[tuple[str, str], FiberSegment], drawn: _DrawnFiber
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
        constraints.number_of_diverse_paths, constraints.seat_cap,
    )
    return sorted(
        independent_paths(site, proof),
        key=lambda path: (path_geometry_miles(path, fiber), path),
    )[: constraints.number_of_diverse_paths]


def _ways_out_of(site: str, drawn: _DrawnFiber) -> list[tuple[str, ...]]:
    """The paths ``site`` is drawn with: what it holds over the fiber the synthesis bought.

    Unless the carrier's whole fiber would have given it more, in which case that is what
    it is drawn with instead. The choice of fiber answers how many ways out a site needs
    without measuring any one path against the operator's backup path multiple, and reading
    the paths back does measure them, so a site can come out of the bought fiber holding
    fewer ways out than the carrier's fiber proves it could hold. A site short of what its
    own fiber supports is the one shortfall
    :func:`synthesizer.stages.finalize` refuses a synthesis over, and it is a shortfall nobody
    can close by buying anything -- so the site is drawn along the paths its fiber proves
    and the synthesis orders the segments they run on.

    Both sets are cut to the tenant's number before they are compared, or a site whose
    fiber offers a third way out would be judged short every time and drawn with fiber
    nobody asked for.
    """
    bought = _proved_over(site, drawn.bought, drawn)
    carrier = _proved_over(site, drawn.carrier, drawn)
    return bought if len(bought) >= len(carrier) else carrier


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
                    path_geometry_miles(path, drawn.carrier), LINK_FOR_TARGET, (site,),
                )
            elif held.reason == LINK_FOR_TARGET and site not in held.requested_by:
                laid[key] = replace(
                    held, requested_by=tuple(sorted((*held.requested_by, site)))
                )
    return [laid[key] for key in sorted(laid)]


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
) -> tuple[frozenset[tuple[str, str]], float, list[SynthesisPath]]:
    """The fiber the synthesis buys, the floor under it, and the paths the operator pinned.

    The pins are drawn over the carrier's whole fiber rather than over what the choice
    bought, and their own segments join what was bought. An operator who writes a pair into
    ``etc/*.yml`` has decided that pair is joined, and a choice made to answer everybody
    else's requirements has no standing to overrule it.
    """
    adjacency = build_adjacency(fiber_segments)
    per_peer = paths_per_peer(
        constraints.seat_cap, len(backbone_ids), constraints.number_of_diverse_paths
    )
    choice = choose_fiber(FiberInputs(
        backbone_ids, fiber_segments, all_distances,
        constraints.number_of_diverse_paths, per_peer, constraints.limit,
    ))
    drawn = (
        _pinned_path(pair, adjacency, fiber_segments)
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
    and every path no site needs is taken back out (see :func:`_needed`). What is published
    is what is left, which is why a published network now holds no path an outside reader
    can remove without costing somebody something -- the property
    ``test_published_syntheses.removable_paths`` measures against the five live maps.

    A backbone the carrier's fiber says nothing about draws nothing, and a node it says
    nothing about is left out while the rest are drawn. The shortfall is
    :func:`synthesizer.validation.backbone_mesh_independence_deficient`'s to report.
    """
    segments, floor, pinned = _bought_fiber(
        backbone_ids, fiber_segments, all_distances, constraints
    )
    bought = {segment: fiber_segments[segment] for segment in sorted(segments)}
    drawn = _DrawnFiber(backbone_ids, bought, fiber_segments, constraints)
    laid = _laid(drawn, pinned)
    return BackboneMesh(
        _needed(laid, backbone_ids, constraints.number_of_diverse_paths), floor
    )
