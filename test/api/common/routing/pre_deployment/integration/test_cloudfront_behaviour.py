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
    if not CLOUDFRONT_TF.exists():
        pytest.skip(f"the sibling checkout is not present at {CLOUDFRONT_TF}")
    patterns = set(_BEHAVIOUR.findall(CLOUDFRONT_TF.read_text(encoding="utf-8")))
    assert f"{urlsplit(DEFAULT_API).path}/*" in patterns
