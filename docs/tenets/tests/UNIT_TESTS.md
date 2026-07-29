# Unit Test Tenets

These are the non-negotiable rules for unit tests. They are pytest tests
under a stack's `pre_deployment/unit/` directory, and they touch nothing
outside the process.

## Table of Contents

- [The Primary Line of Defense](#the-primary-line-of-defense)
- [One Assert Per Test](#one-assert-per-test)
- [Test File Organization](#test-file-organization)
- [Complete Isolation](#complete-isolation)
- [Test Every Branch](#test-every-branch)
- [Descriptive Test Names](#descriptive-test-names)
- [Every Test Carries a Docstring](#every-test-carries-a-docstring)
- [Assertions That Explain Themselves](#assertions-that-explain-themselves)
- [No Test Interdependence](#no-test-interdependence)
- [No Duplicated Setup](#no-duplicated-setup)
- [Fast Execution](#fast-execution)
- [Typed and Lint-Clean](#typed-and-lint-clean)
- [What Unit Tests Must Catch](#what-unit-tests-must-catch)
- [Quick Reference](#quick-reference)

## The Primary Line of Defense

Almost everything wrong should be caught by a unit test.

The pyramid puts unit tests at the base, and the count should be far
larger than every other tier combined. If a bug could have been caught by
a unit test and was not, that is a coverage failure, not bad luck.

```text
        /\
       /  \     End to end (one entrypoint)
      /----\
     /      \   Integration (some)
    /--------\
   /          \
  /            \ Unit (many)
 /______________\
```

The dividing line is dependencies, not I/O. If the test exercises one
module with everything else supplied as a literal or a double, it is a
unit test. If it exercises two or more modules against each other, it is
an integration test, whether or not anything leaves the process.

## One Assert Per Test

Each test verifies exactly one behaviour, with exactly one `assert`.

This is not a style preference. `assert-one-assert-per-pytest` runs as a
static-analysis step in every workflow, so a second assert fails the
build before any test executes.

```python
def test_backbone_mesh_paths_empty_when_nodes_disconnected() -> None:
    """Backbone mesh paths empty when the backbone nodes are disconnected."""
    edges = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest(
        [pop("a"), pop("b"), pop("c"), pop("d")], adjacency
    )
    assert not backbone_mesh_paths(("a", "c"), distances, predecessors, edges)
```

When two facts need asserting, write two tests. Setup they share belongs
in a helper or a fixture, not in a second assert.

```python
def test_timeout_matches_declaration(parsed: Tuning) -> None:
    """The parsed timeout matches the declared value."""
    assert parsed.timeout == 10


def test_memory_matches_declaration(parsed: Tuning) -> None:
    """The parsed memory matches the declared value."""
    assert parsed.memory == 128
```

Use `pytest.mark.parametrize` when the same single assertion applies over
a set of inputs. That stays one assert and keeps each case named in the
failure output.

```python
@pytest.mark.parametrize("variable", ["STORE_BUCKET"])
def test_environment_variable_is_set(
        lambda_config: dict[str, Any], variable: str) -> None:
    """The live Lambda carries each environment variable it reads."""
    assert variable in lambda_config["Environment"]["Variables"]
```

## Test File Organization

One test file per source module, named for the module it covers.

```text
src/api/endpoints/tenants/wan/post/lambdas/synthesizer/
├── backbone.py
├── config.py
├── strength.py
├── synthesize.py
└── validation.py

test/api/endpoints/tenants/wan/post/pre_deployment/unit/
├── test_backbone.py      # Covers backbone.py
├── test_config.py        # Covers config.py
├── test_synthesize.py    # Covers synthesize.py
└── test_validate_design.py
```

Do not organise by behaviour: there is no `test_happy_path.py` and no
`test_error_cases.py`. Do not cover two source modules from one test
file, and do not split one module's tests across several files without a
reason the file names make obvious.

## Complete Isolation

A unit test has zero external dependencies.

- No network calls, including boto3 calls against real AWS.
- No file system writes, and reads only of committed inputs.
- No subprocesses.
- No environment variable left mutated after the test.

Use the doubles in `lib/python/` rather than reaching for a live client.

```python
from test_module_utils import create_lambda_loader
from test_s3_store_mock import fake_s3

def test_handler_reads_the_stored_document() -> None:
    """The handler returns the document stored under the requested key."""
    handler = load_handler("tenants", monkeypatch, STORE_BUCKET="bucket")
    handler.s3 = fake_s3({"tenants/daf/knobs.json": b"{}"})
    assert handler.lambda_handler(event, None)["statusCode"] == 200
```

Set environment variables through `monkeypatch`, never through `os.environ`
directly, so the change is undone when the test ends.

## Test Every Branch

The gate is 100% branch coverage, and it is enforced.

```text
--cov=src/api/endpoints/tenants/lambdas
--cov-branch
--cov-report=term-missing
--cov-fail-under=100
```

Every `if`, `else`, `except`, early return and loop exit needs a test.
A new branch without a test does not merely go unverified, it turns the
unit-tests job red and blocks reconciliation.

The `--pythonwarnings=error` flag is set alongside the coverage flags, so
a `DeprecationWarning` raised during a unit test is a failure too.

## Descriptive Test Names

The name states the subject, the condition and the expected result, so a
failure in the log is legible without opening the file.

```python
def test_backbone_mesh_paths_empty_when_nodes_disconnected() -> None: ...
def test_seed_cli_fails_when_the_api_rejects_writes() -> None: ...
def test_role_grants_store_access() -> None: ...
```

Names like `test_config`, `test_it_works` or `test_error_handling` say
nothing and are not acceptable.

## Every Test Carries a Docstring

pylint runs with `--fail-on=C,R,W`, so a missing docstring is a failed
build. Write the sentence the name could not fit, in the present tense,
describing the behaviour rather than the mechanics.

```python
def test_enum_memory_fraction_above_one_is_rejected() -> None:
    """A memory fraction above 1 is rejected when the config is parsed."""
```

Do not restate the function name in prose, and do not describe the setup
the reader can see two lines below.

## Assertions That Explain Themselves

Assert the specific value, not its truthiness.

```python
def test_runtime_is_python313(lambda_config: dict[str, Any]) -> None:
    """The live Lambda runs on Python 3.13."""
    assert lambda_config["Runtime"] == "python3.13"
```

An `assert result` tells the reader nothing when it fails. Compare
against the expected value so pytest can print both sides. Where the
subject is a collection, assert the membership or the count that matters,
not that the collection is non-empty.

For raised errors, assert the type and the text that identifies it, using
`pytest.raises` with `match` so the two stay one assertion.

```python
def test_parse_rejects_a_zero_sector_count() -> None:
    """A sector count of 0 is rejected with a message naming the key."""
    with pytest.raises(ValueError, match="compass_octants"):
        app_config_from_parts(parts_with(compass_octants=0))
```

## No Test Interdependence

Each test passes on its own, in any order, with no shared mutable state.

Build state inside the test or in a function-scoped fixture. A
module-level mutable object that tests write to couples them, and the
failure surfaces as an unrelated test breaking when a new one is added.

```python
@pytest.fixture(name="design")
def design_fixture() -> DesignArtifacts:
    """Build a fresh two-tier design over the ring fixture."""
    return fixtures.run_design()
```

Module-level constants are fine when they are immutable inputs, which is
how the synthesizer's distance tables are written.

## No Duplicated Setup

`jscpd` runs over the test tree at a zero-tolerance threshold, so a
copied block of setup fails the build.

Shared inputs go in `test/fixtures.py` when they are graphs, vertices or
designs, in the stack's `conftest.py` when they are stack-specific, and
in `lib/python/` when more than one stack needs them. A local helper
function at the top of the test module is the right answer when the reuse
is confined to that module.

## Fast Execution

Unit tests are measured in milliseconds.

If one takes noticeable time, the cause is nearly always that it is not a
unit test any more: something is reaching the network, walking a real
graph at production scale, or spawning a process. Move it to the tier it
belongs in rather than accepting the cost.

## Typed and Lint-Clean

Tests are held to the same static analysis as source. mypy runs with
`--strict` over the test tree, so every test function is annotated,
including the `-> None` return.

```python
def test_iam_role_exists(iam_client: Any, role_name: str) -> None:
    """The Lambda execution role exists."""
    role = iam_client.get_role(RoleName=role_name)
    assert role["Role"]["RoleName"] == role_name
```

Suppressing a finding inline is not available: `assert-no-inline-directives`
fails on a `# pylint: disable` or `# type: ignore` comment, and
`assert-no-linter-config-files` fails on a configuration file that would
relax the rule globally. Fix the code instead.

## What Unit Tests Must Catch

| Issue | Caught by |
| --- | --- |
| Import and syntax errors | Unit |
| Type mismatches | Unit and mypy |
| Missing input validation | Unit |
| Edge cases and empty inputs | Unit |
| Business logic errors | Unit |
| Error paths and messages | Unit |
| Single-file config parsing | Unit |
| Cross-file contract drift | Pre-deployment integration |
| Credentials and permissions | Pre-deployment integration |
| State drift | Pre-deployment integration |
| Resource misconfiguration | Post-deployment integration |
| Component wiring | Post-deployment integration |
| Whole-entrypoint behaviour | End to end |

## Quick Reference

| To test | Tier |
| --- | --- |
| A function's return value | Unit |
| An error raised for bad input | Unit |
| A parsed configuration value | Unit |
| A handler's response shape | Unit |
| Two modules agreeing | Pre-deployment integration |
| Declared state matching AWS | Pre-deployment integration |
| A live resource's settings | Post-deployment integration |
| A live resource's connections | Post-deployment integration |
| The seed CLI end to end | End to end |
