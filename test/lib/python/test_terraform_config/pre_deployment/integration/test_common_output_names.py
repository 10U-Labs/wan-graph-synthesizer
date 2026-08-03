"""Contract: the outputs this module reads by name are ones the common module declares.

The module reads three outputs out of ``lib/opentofu/common/outputs.tf`` under names
written into its own code -- ``aws_region``, ``state_bucket`` and ``lambda_handler_names``
-- and hands the first two to every test in the suite as constants. Those names are a
contract with the declaration, and only the declaration can settle it: renaming an output
there is a change no test of this module on its own would notice.

What it costs is that the fallback wins in silence. ``_string_output`` answers with the
literal written beside the read when the name is not declared, so a renamed output leaves
every client built for a region nobody deploys to, every probe reporting resources absent
that are present, and no failure anywhere naming the output that moved. Reading the
declared value back and comparing it is what turns that into one failure here.
"""

from __future__ import annotations

from test_terraform_config import (
    COMMON_OUTPUTS_FILE,
    STATE_BUCKET,
    TEST_AWS_REGION,
    common_outputs,
    lambda_handler_names,
)

# The three output names written into this module's own code.
_NAMES_READ = ("aws_region", "state_bucket", "lambda_handler_names")


def test_the_common_module_the_reads_point_at_is_there() -> None:
    """A moved or renamed file fails here rather than inside the first client a test builds."""
    assert COMMON_OUTPUTS_FILE.is_file() is True


def test_every_output_the_module_reads_by_name_is_declared() -> None:
    """No name the module reaches for is one the common module has stopped declaring."""
    declared = common_outputs()
    assert [name for name in _NAMES_READ if name not in declared] == []


def test_the_region_every_client_is_built_for_is_the_declared_one() -> None:
    """The constant is the declaration and not the literal the read falls back to."""
    assert TEST_AWS_REGION == common_outputs()["aws_region"]


def test_the_state_bucket_the_suite_inspects_is_the_declared_one() -> None:
    """Same for the bucket the authorization layer proves it may read."""
    assert STATE_BUCKET == common_outputs()["state_bucket"]


def test_every_declared_handler_name_survives_being_offered() -> None:
    """The mapping handed to callers holds each resource the declaration names."""
    assert lambda_handler_names() == common_outputs()["lambda_handler_names"]
