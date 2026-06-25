"""Layer 2 (authentication): valid AWS credentials before reconciling merge."""
from __future__ import annotations

from test_fixtures.integration import create_simple_layer1_authentication_tests

TestAWSAuthentication = create_simple_layer1_authentication_tests()
