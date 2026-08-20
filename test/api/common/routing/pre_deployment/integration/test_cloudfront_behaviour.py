"""Contract: the prefix this product serves is one CloudFront carries to the gateway.

Every caller outside AWS reaches the API through a CloudFront distribution declared in
``10U-Labs/10ulabs.com``, not here: an ``ordered_cache_behavior`` matches the served
prefix and sends it to this repository's API Gateway. The two repositories deploy from
workflows that order nothing between them, so a prefix that moves here before a behaviour
exists there is the whole API answering from a different origin, and nothing in this
repository would say so until a request failed.

This is a file read of the sibling checkout, not an AWS call, so it costs nothing and it
is the only way this repository can be told the two disagree before a deploy proves it.
It is skipped where that checkout is absent, which is every CI runner -- a workflow checks
out one repository -- so it answers for somebody working on both at once.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import pytest

from repo_utils import REPO_ROOT
from seed import DEFAULT_API

CLOUDFRONT_TF = (
    REPO_ROOT.parent / "10ulabs.com" / "src" / "api" / "common" / "routing"
    / "cloudfront_s3.tf"
)

_BEHAVIOUR = re.compile(
    r"ordered_cache_behavior\s*\{[^}]*?path_pattern\s*=\s*\"([^\"]+)\"", re.S
)


def test_the_served_prefix_has_a_behaviour_carrying_it() -> None:
    """Some behaviour in the sibling distribution matches the prefix seed sends to.

    Membership rather than equality: while a prefix is moving, the old behaviour and the
    new one are both declared on purpose, and a behaviour left behind afterwards serves
    the same origin under an address nothing sends to.
    """
    if not CLOUDFRONT_TF.exists():
        pytest.skip(f"the sibling checkout is not present at {CLOUDFRONT_TF}")
    patterns = set(_BEHAVIOUR.findall(CLOUDFRONT_TF.read_text(encoding="utf-8")))
    assert f"{urlsplit(DEFAULT_API).path}/*" in patterns
