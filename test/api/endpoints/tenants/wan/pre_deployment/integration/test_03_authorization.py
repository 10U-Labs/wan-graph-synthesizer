"""Layer 3 (authorization): permission to inspect the shared state bucket."""
from __future__ import annotations

from test_fixtures.integration import create_layer2_s3_authorization_tests

TestS3Authorization = create_layer2_s3_authorization_tests()
