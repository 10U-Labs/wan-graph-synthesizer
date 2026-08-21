"""Seed the wan-synthesizer API from the git-authored data/ + etc/ inputs.

A plain reader-and-sender: read each cleaned CSV into simple rows (city, state,
latitude, longitude, plus a name where the source has one) and PUT them to the matching
endpoint. What each place *is* comes from the endpoint it is sent to, so nothing is
classified or shaped here; carrier fiber segments (``A_/Z_`` city+state) are forwarded
as they stand and resolved server-side. Carriers push their points and fiber segments;
providers push their regions; each tenant pushes its sites, provider-region selection,
off-net candidates, and per-concern config resources. The tenant configs in ``etc/`` are
the roster, so a tenant the API still lists once they have all been pushed is one git no
longer declares and is deleted. Writes only store inputs -- they trigger
nothing -- so the seed then explicitly rebuilds the merged carriers
(``POST carriers/merge``) and each tenant's WAN (``POST tenants/{t}/wan``). Renaming a
collection leaves its old object where it was, so the seed also asks the store to take
out everything held under a name the product no longer writes
(``POST store/prune``).

Usage: python scripts/seed.py [api_base_url]
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import yaml

from repo_utils import REPO_ROOT

DEFAULT_API = "https://api.10ulabs.com/wan-synthesizer"
# How long _send waits before trying a dropped connection a second time.
RETRY_PAUSE_SECONDS = 1.0
DATA = REPO_ROOT / "data"
ETC = REPO_ROOT / "etc"


def _rows(path: Path) -> list[dict[str, Any]]:
    """Read a cleaned CSV into simple rows: lowercased keys, numeric lat/lon."""
    if not path.exists():
        raise ValueError(f"Input file does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows: list[dict[str, Any]] = []
        for raw in csv.DictReader(handle):
            row: dict[str, Any] = {key.lower(): value.strip() for key, value in raw.items()}
            if "latitude" in row:
                row["latitude"] = float(row["latitude"])
                row["longitude"] = float(row["longitude"])
            rows.append(row)
        return rows


def _mapping_rows(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a ``{label: csv-or-list}`` inputs mapping into one list of rows.

    The labels group the source files but are not the owner -- the tenant is -- so they
    are dropped and every file's rows are concatenated. ``inputs.locations`` is the one
    block shaped this way, because a tenant may legitimately draw its sites from several
    files; ``inputs.providers`` names its single file directly and is read as a path.
    """
    rows: list[dict[str, Any]] = []
    for value in mapping.values():
        for raw in value if isinstance(value, list) else [value]:
            rows.extend(_rows(REPO_ROOT / raw))
    return rows


def _city_key(row: dict[str, Any]) -> tuple[str, str]:
    """A geographic row's ``(municipality, state)`` identity, case-folded.

    The synthesizer keys carrier points by that pair verbatim, so two spellings that
    differ only in case become two separate cities there. Folding here means such a
    pair is caught rather than waved through as a distinct place.
    """
    return str(row["municipality"]).casefold(), str(row["state"]).casefold()


def _carrier_cities() -> set[tuple[str, str]]:
    """Every city a pushed carrier has a point in, read off the roster _carrier_names gives.

    The roster is the fiber files, so a carrier with points and no fiber contributes
    nothing here. That is what the merged carriers do too: ``synthesizer.codec`` drops a
    point no fiber segment touches before any synthesis starts, so such a city can hold
    no backbone node and is genuinely free for an off-net seat. Globbing the points
    directory instead answered the question from a second roster that could disagree
    with the one ``push_carriers`` acts on.
    """
    return {
        _city_key(row)
        for carrier in _carrier_names()
        for row in _rows(DATA / "pops" / f"{carrier}.csv")
    }


def _off_net_rows(path: str) -> list[dict[str, Any]]:
    """Read the seats a config's ``inputs.forced`` names, refusing any carrier city.

    An off-net seat is a location with no carrier point of its own, offered to the
    operator as somewhere a backbone node may be built out of local fiber -- which is
    why the config names the file under ``forced``: nothing in it is read unless the
    operator forces that seat into the backbone. A row naming
    a city a carrier already serves is therefore a contradiction, and a silent one: the
    synthesizer seats the operator's pin on the real point and skips the row, so the
    file claims a seat it never provides. This is the only reader of the file that also
    holds the carrier points, so it is the only place the pair can be checked.
    """
    rows = _rows(REPO_ROOT / path)
    carriers = _carrier_cities()
    on_net = sorted(
        f"{row['municipality']}, {row['state']}"
        for row in rows if _city_key(row) in carriers
    )
    if on_net:
        raise ValueError(
            f"off-net file {path} names cities a carrier already serves: "
            f"{'; '.join(on_net)}")
    return rows


def _slug(stem: str) -> str:
    """A url-safe resource id from a file stem (underscores become hyphens)."""
    return stem.replace("_", "-")


def _is_dropped_connection(failure: OSError) -> bool:
    """Whether *failure* is the peer dropping the connection with no answer behind it.

    A reset reaches the caller two ways: raised as it stands when the connection dies
    while the body is being read, and wrapped in a ``urllib.error.URLError`` when it dies
    during the TLS handshake. An ``HTTPError`` is the service answering and is never one
    of these, and a ``URLError`` for any other reason -- a name that does not resolve, a
    host that refuses -- is a failure a second attempt would meet again.
    """
    if isinstance(failure, urllib.error.HTTPError):
        return False
    if isinstance(failure, urllib.error.URLError):
        return isinstance(failure.reason, ConnectionResetError)
    return isinstance(failure, ConnectionResetError)


def _send_once(request: urllib.request.Request, method: str, path: str) -> bytes:
    """Make one attempt at *request* and return its body, raising on a non-2xx response."""
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"  {method} /{path} -> {response.status}", flush=True)
        return cast("bytes", response.read())


def _send(api: str, path: str, method: str, body: bytes | None) -> bytes:
    """Send a JSON request to the API and return its body, raising on a non-2xx response.

    A connection the peer resets is tried a second time, after RETRY_PAUSE_SECONDS, and a
    second reset raises. The seeding pass and the end-to-end tier together make around
    ninety requests to api.10ulabs.com, TLS connections there are reset now and then, and
    one such reset used to fail the whole run (GitHub issue #105). Retrying is safe here
    because a reset is the connection dying with no response behind it, so there is no
    request the service may already have acted on.
    """
    request = urllib.request.Request(
        f"{api}/{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        return _send_once(request, method, path)
    except OSError as failure:
        if not _is_dropped_connection(failure):
            raise
    print(f"  {method} /{path} -> connection reset, trying once more", flush=True)
    time.sleep(RETRY_PAUSE_SECONDS)
    return _send_once(request, method, path)


def _put(api: str, path: str, body: Any) -> None:
    """PUT a JSON body to an API collection, raising on a non-2xx response."""
    _send(api, path, "PUT", json.dumps(body).encode())


def _post(api: str, path: str) -> None:
    """POST to a build operation (no body), raising on a non-2xx response."""
    _send(api, path, "POST", b"")


def _post_json(api: str, path: str) -> Any:
    """POST to an operation and read its JSON answer, raising on a non-2xx response."""
    return json.loads(_send(api, path, "POST", b""))


def _get(api: str, path: str) -> Any:
    """GET a JSON document from the API, raising on a non-2xx response."""
    return json.loads(_send(api, path, "GET", None))


def _delete(api: str, path: str) -> None:
    """DELETE a resource from the API, raising on a non-2xx response."""
    _send(api, path, "DELETE", None)


def _degree_doc(value: Any) -> dict[str, Any]:
    """Wrap a required redundancy degree as its ``{"degree": int}`` document."""
    return {"degree": value}


def _carrier_names() -> list[str]:
    """The carriers: the stems of the fiber files under ``data/fiber_segments``, sorted.

    The fiber decides, because a carrier with no fiber can carry nothing -- its points
    are dropped by ``synthesizer.codec`` before any synthesis starts. Each carrier's
    points are then read from ``data/pops/`` by the stem its fiber file
    gave, so a fiber file with no points file beside it is not skipped: it stops the
    seed with the ``Input file does not exist`` that ``_rows`` raises.
    """
    return sorted(p.stem for p in (DATA / "fiber_segments").glob("*.csv"))


def push_carriers(api: str) -> None:
    """Push each carrier's points and fiber segments as simple rows."""
    for carrier in _carrier_names():
        cid = _slug(carrier)
        pops = _rows(DATA / "pops" / f"{carrier}.csv")
        fiber_segments = _rows(DATA / "fiber_segments" / f"{carrier}.csv")
        print(f"carrier {cid}: {len(pops)} points, "
              f"{len(fiber_segments)} fiber segments", flush=True)
        _put(api, f"carriers/{cid}/pops", pops)
        _put(api, f"carriers/{cid}/fiber-segments", fiber_segments)


def push_providers(api: str) -> None:
    """Push the provider regions (a single combined regions file)."""
    regions = _rows(DATA / "providers" / "providers.csv")
    print(f"providers: {len(regions)} regions", flush=True)
    _put(api, "providers/regions", regions)


def push_tenants(api: str) -> list[str]:
    """Push each tenant's inputs and return the tenant ids (for the build step).

    A tenant whose sites are its whole demand names no file under ``inputs.providers``
    and is pushed an empty ``provider-regions`` document. The document is still written,
    because the synthesizer reads every config resource and a missing one is a failed
    build rather than a tenant with no cloud regions.
    """
    tenant_ids: list[str] = []
    for path in sorted(ETC.glob("*.yml")):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not config:
            continue
        tid = _slug(path.stem)
        tenant_ids.append(tid)
        inputs = config.get("inputs", {})
        access = config["access"]
        backbone = config["backbone"]
        forced = backbone.get("forced", {})
        prohibited = backbone.get("prohibited", {})
        homes = access.get("forced", {}).get("homes", [])
        locations = _mapping_rows(inputs.get("locations", {}))
        regions = _rows(REPO_ROOT / inputs["providers"]) if inputs.get("providers") else []
        off_net_file = inputs.get("forced")
        off_net = _off_net_rows(off_net_file) if off_net_file else []
        print(f"tenant {tid}: {len(locations)} sites, {len(regions)} regions, "
              f"{len(off_net)} off-net", flush=True)
        _put(api, f"tenants/{tid}/locations", locations)
        _put(api, f"tenants/{tid}/provider-regions", regions)
        _put(api, f"tenants/{tid}/off-net", off_net)
        _put(api, f"tenants/{tid}/forced-backbone-nodes", forced.get("nodes", []))
        _put(api, f"tenants/{tid}/forced-paths", forced.get("paths", []))
        _put(api, f"tenants/{tid}/forced-homes", homes)
        _put(api, f"tenants/{tid}/prohibited-backbone-nodes", prohibited.get("nodes", []))
        _put(api, f"tenants/{tid}/prohibited-paths", prohibited.get("paths", []))
        # The nodes held to no diverse path count. A config naming none says so with an empty
        # document rather than by leaving the resource absent, since the synthesizer
        # reads every config resource and a missing one is a failed build.
        _put(api, f"tenants/{tid}/degree-exempt-backbone-nodes",
             backbone.get("degree_exempt", []))
        _put(api, f"tenants/{tid}/backbone-node-count", backbone.get("node_count", {}))
        _put(api, f"tenants/{tid}/backbone-number-of-diverse-paths",
             _degree_doc(backbone["number_of_diverse_paths"]))
        _put(api, f"tenants/{tid}/access-homing-degree",
             _degree_doc(access["homing_degree"]))
        _put(api, f"tenants/{tid}/convergence-promotion",
             {"promote": backbone["promote_high_degree_convergences"]})
        # The stored documents keep the unshortened keys: the config drops the prefix its
        # block now supplies, but the synthesizer reads both values under the long names.
        # The backup path multiple rides the knobs resource rather than taking one of its
        # own, which is what keeps a seed run from racing an endpoint the API does not
        # define yet.
        _put(api, f"tenants/{tid}/knobs", {
            "backbone_coverage_target_miles": backbone["coverage_target_miles"],
            "backbone_max_backup_path_multiple": backbone["max_backup_path_multiple"],
        })
        _put(api, f"tenants/{tid}/settings", config.get("settings", {}))
        _put(api, f"tenants/{tid}/label", {"label": config.get("label", "")})
    return tenant_ids


def prune_tenants(api: str, tenants: list[str]) -> None:
    """Delete every stored tenant that ``etc/`` no longer declares.

    ``etc/`` is the roster: a tenant exists because a config file names it, so one the
    API still lists after the push is a tenant git has dropped, and its stored inputs
    and WAN go with it.
    """
    for entry in _get(api, "tenants"):
        tenant = entry["id"]
        if tenant in tenants:
            continue
        print(f"tenant {tenant}: deleting (no config in etc/)", flush=True)
        _delete(api, f"tenants/{tenant}")


def prune_store(api: str) -> None:
    """Take the objects nothing writes any more out of the store, and name what went.

    Renaming a collection writes the new key and leaves the old one behind, and a leftover
    is not inert: ``carriers/lumen/vertices.json`` was merged in as fiber and failed every
    tenant's build on 2026-08-20 (GitHub issue #102). The push above has just written
    every collection the product does write, so anything else the store is holding is a
    collection that has been renamed out from under it.

    The keys are printed rather than counted, because this runs in the ``seeding`` job's
    log and somebody reading it back needs to see what went, not how much.

    An answer of some other shape costs the log line and not the run. The store has already
    pruned by the time its answer is read, so a seed that raised here would fail a run whose
    work was done, over the part of it that is only a courtesy.
    """
    print("store: pruning collections nothing writes any more", flush=True)
    answer = _post_json(api, "store/prune")
    deleted = answer.get("deleted", []) if isinstance(answer, dict) else []
    for key in deleted:
        print(f"  deleted {key}", flush=True)


def build_merged_carriers(api: str) -> None:
    """Rebuild the merged carriers from the carriers just pushed."""
    print("merge: rebuilding the merged carriers", flush=True)
    _post(api, "carriers/merge")


def build_tenants(api: str, tenants: list[str]) -> None:
    """Trigger one WAN build per tenant (the only build trigger)."""
    for tid in tenants:
        print(f"tenant {tid}: building WAN", flush=True)
        _post(api, f"tenants/{tid}/wan")


def main() -> None:
    """Seed inputs, prune what git dropped, then rebuild the merged carriers and each WAN."""
    api = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    push_carriers(api)
    build_merged_carriers(api)
    push_providers(api)
    tenants = push_tenants(api)
    prune_tenants(api, tenants)
    prune_store(api)
    build_tenants(api, tenants)


if __name__ == "__main__":  # pragma: no cover
    main()
