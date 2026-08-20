"""Whether the seed left the store holding only what the product writes.

Renaming a collection writes the new key and leaves the old one where it was, and a
leftover is not inert: ``carriers/lumen/vertices.json`` was merged in as fiber and failed
every tenant's build on 2026-08-20 (GitHub issue #102). ``scripts/seed.py`` asks the store
to prune on every run, and this is the assertion that the ask actually landed.

It runs here rather than in ``api_common_storage`` because the prune is run by the
``seeding`` job of this workflow, and the storage workflow is not ordered against it: an
assertion there would be reading the store before anything had pruned it, which is how it
failed on 98a6a6f. Where a test sits follows what delivers the thing it checks.

Read through ``GET /wan-synthesizer/store/prune``, which names what is stale and deletes
nothing. That is the whole reason the route answers a read as well as a write, and it
keeps this tier what it already is: the public API and no AWS client.
"""
from __future__ import annotations

from seed import DEFAULT_API, _get


def test_the_seeded_store_holds_nothing_the_product_no_longer_writes() -> None:
    """Every object the store holds after a seed is one the product writes today.

    A rename that lands without the prune running leaves its old object behind, and the
    next reader that lists a prefix meets it as though it were current. Nothing else out
    here would say so: every read endpoint serves the key it names and never notices what
    else is beside it.
    """
    assert _get(DEFAULT_API, "store/prune")["stale"] == []
