from __future__ import annotations

from seed import DEFAULT_API, _get


def test_the_seeded_store_holds_nothing_the_product_no_longer_writes() -> None:
    assert _get(DEFAULT_API, "store/prune")["stale"] == []
