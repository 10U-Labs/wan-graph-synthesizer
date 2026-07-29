# Post-Deployment Integration Test Tenets

These are the non-negotiable rules for post-deployment integration tests.
They live under a stack's `post_deployment/integration/` directory and
run against live AWS after the `reconciliation` job has applied the
stack.

## Table of Contents

- [Only This Stack's Resources](#only-this-stacks-resources)
- [The Three-Layer Model](#the-three-layer-model)
- [Test File Organization](#test-file-organization)
- [Layer 1, Existence](#layer-1-existence)
- [Layer 2, Configuration](#layer-2-configuration)
- [Layer 3, Wiring](#layer-3-wiring)
- [Assert Against the Declaration](#assert-against-the-declaration)
- [Inspect, Never Invoke](#inspect-never-invoke)
- [No Cleanup Required](#no-cleanup-required)
- [Fail Fast with Granular Diagnostics](#fail-fast-with-granular-diagnostics)
- [Fixture Usage](#fixture-usage)
- [Position in the Workflow](#position-in-the-workflow)
- [Quick Reference](#quick-reference)

## Only This Stack's Resources

A post-deployment test inspects what this workflow's `tofu apply` just
created, and nothing else.

- Do test: the resources this stack declares.
- Do test: their configuration against the declaration.
- Do test: the connections between them.
- Do NOT test: resources another workflow owns. Their own workflow tests
  them, and asserting on them here couples two stacks that are otherwise
  independent.
- Do NOT test: application logic. That is a unit test, and it has
  already run.
- Do NOT test: behaviour that requires invoking anything.

## The Three-Layer Model

Every deployed resource is checked through three layers, in order.

| Layer | Question |
| --- | --- |
| 1. Existence | Was it created? |
| 2. Configuration | Does it match the declaration? |
| 3. Wiring | Is it connected to its neighbours? |

Each layer isolates a different failure.

- Layer 1 fails: the apply did not create the resource.
- Layer 2 fails: it exists but carries the wrong settings.
- Layer 3 fails: it exists and is configured, but nothing can reach it
  or it cannot reach what it needs.

## Test File Organization

Tests are organised into exactly three files, one per layer.

```text
test/api/endpoints/<endpoint>/post_deployment/
├── conftest.py                    # Re-exports the boto3 clients used
└── integration/
    ├── conftest.py                # Fixtures fetched once per module
    ├── test_01_existence.py       # Layer 1
    ├── test_02_configuration.py   # Layer 2
    └── test_03_wiring.py          # Layer 3
```

Do not organise by resource. A `test_lambda.py` alongside a `test_iam.py`
hides which layer broke, and the layer is the diagnostic.

## Layer 1, Existence

Existence only. No settings, no connections.

```python
"""Layer 1 (existence): the tenants stack's resources exist in AWS."""
from test_fixtures.aws import get_log_group_info


def test_lambda_function_exists(
        lambda_config: dict[str, Any], function_name: str) -> None:
    """The tenants handler Lambda exists under its deterministic name."""
    assert lambda_config["FunctionName"] == function_name


def test_iam_role_exists(iam_client: Any, role_name: str) -> None:
    """The Lambda execution role exists."""
    role = iam_client.get_role(RoleName=role_name)
    assert role["Role"]["RoleName"] == role_name


def test_log_group_exists(logs_client: Any, function_name: str) -> None:
    """The handler's CloudWatch log group exists."""
    info = get_log_group_info(logs_client, f"/aws/lambda/{function_name}")
    assert info["exists"]
```

Folding a timeout assertion into the existence test would mean a
configuration drift reports as a missing resource.

## Layer 2, Configuration

Settings only, assuming existence has passed.

```python
def test_runtime_is_python313(lambda_config: dict[str, Any]) -> None:
    """The live Lambda runs on Python 3.13."""
    assert lambda_config["Runtime"] == "python3.13"


def test_timeout_is_ten_seconds(lambda_config: dict[str, Any]) -> None:
    """The live Lambda's timeout matches the declaration."""
    assert lambda_config["Timeout"] == 10


def test_entrypoint(lambda_config: dict[str, Any]) -> None:
    """The live Lambda invokes ``handler.lambda_handler``."""
    assert lambda_config["Handler"] == "handler.lambda_handler"
```

Do not re-fetch a resource to prove it is there before reading a setting.
The fixture already holds it, and the extra call is a second assertion
wearing a disguise.

## Layer 3, Wiring

Connections only, assuming existence and configuration have passed.

```python
def test_lambda_assumes_the_declared_role(
        lambda_config: dict[str, Any], role_name: str) -> None:
    """The live Lambda runs as the declared execution role."""
    assert lambda_config["Role"].endswith(f"role/{role_name}")


def test_api_gateway_may_invoke_the_lambda(
        lambda_client: Any, function_name: str) -> None:
    """API Gateway holds permission to invoke the live Lambda."""
    policy = lambda_client.get_policy(FunctionName=function_name)["Policy"]
    assert "apigateway.amazonaws.com" in policy


def test_role_grants_store_access(iam_client: Any, role_name: str) -> None:
    """The execution role grants the Lambda read/write access to the store."""
    policy = iam_client.get_role_policy(
        RoleName=role_name, PolicyName="StoreAccess")
    assert "s3:GetObject" in str(policy["PolicyDocument"])
```

Wiring is the layer that catches what the other two cannot: a permission
that was never attached, a role the function does not actually assume, a
trigger nothing registered.

## Assert Against the Declaration

Where a value is derived rather than chosen, read it from the same source
the stack does instead of copying the literal into the test.

The stack's `conftest.py` parses the declared OpenTofu configuration and
exposes `function_name` and `role_name`. A test that hardcodes the name
passes while the stack renames the resource underneath it, which is
exactly the drift this tier exists to catch.

Fixed values that the declaration itself states, such as a timeout of 10
or a runtime of `python3.13`, are written as literals on purpose: the
test is the second opinion, and deriving both sides from one source would
assert nothing.

## Inspect, Never Invoke

If a test invokes a Lambda, sends an HTTP request or enqueues a message,
it has left this tier.

```python
def test_handler_returns_200(lambda_client: Any, function_name: str) -> None:
    """The handler answers an invocation."""
    response = lambda_client.invoke(
        FunctionName=function_name, Payload=b"{}")
    assert response["StatusCode"] == 200
```

That is not a post-deployment test. Handler behaviour is covered by unit
tests over the handler module, and whole-entrypoint behaviour by the
end-to-end tier described in [E2E_TESTS.md](E2E_TESTS.md).

The permitted calls are the read-only ones: `get_function`,
`get_function_configuration`, `get_policy`, `get_role`,
`get_role_policy`, `describe_log_groups` and their equivalents.

## No Cleanup Required

Post-deployment tests create nothing, so they clean up nothing.

- Do: read configuration.
- Do: read policies and role documents.
- Do NOT: write an object, a record or a message anywhere.

A test that needs cleanup is in the wrong tier. Move it.

## Fail Fast with Granular Diagnostics

- One assert per test, enforced by `assert-one-assert-per-pytest`.
- Layers run in numeric order, so the first failure names the stage.
- Assert the specific value, so pytest prints both sides.
- Name the resource in the assertion, not just the attribute.

## Fixture Usage

Two levels of `conftest.py` carry this tier. The tier root re-exports the
boto3 clients its tests use:

```python
"""Boto3 client fixtures shared by the tenants post-deployment tier."""
from test_fixtures.aws import iam_client, lambda_client, logs_client

__all__ = ["iam_client", "lambda_client", "logs_client"]
```

The integration directory derives anything fetched once and shared by the
three layers, so the tier costs one API call rather than one per test:

```python
@pytest.fixture(name="lambda_config")
def lambda_config_fixture(
        lambda_client: Any, function_name: str) -> dict[str, Any]:
    """Return the live tenants Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=function_name)
    return cast("dict[str, Any]", response["Configuration"])
```

`function_name` and `role_name` come from the stack's `conftest.py`,
which parses the declaration. Do not re-derive them here.

## Position in the Workflow

```text
static-analysis
  └── unit-tests
        └── pre-deployment-integration-tests
              └── reconciliation
                    └── post-deployment-integration-tests
```

The job assumes the OIDC role and runs pytest against live AWS. It needs
no OpenTofu setup, because it reads AWS rather than state.

```yaml
- name: Run post-deployment integration tests against live AWS
  run: >-
    PYTHONPATH=.:lib/python
    python3 -m pytest
    test/api/endpoints/tenants/post_deployment/integration/
    --import-mode=importlib --confcutdir=test
    --verbose
```

Like reconciliation, it is gated on `github.ref == 'refs/heads/main'`.

## Quick Reference

| To test | Layer | File |
| --- | --- | --- |
| A Lambda exists | 1 | `test_01_existence.py` |
| An IAM role exists | 1 | `test_01_existence.py` |
| A log group exists | 1 | `test_01_existence.py` |
| Runtime and architecture | 2 | `test_02_configuration.py` |
| Timeout and memory | 2 | `test_02_configuration.py` |
| Environment variables set | 2 | `test_02_configuration.py` |
| The Lambda assumes its role | 3 | `test_03_wiring.py` |
| API Gateway may invoke it | 3 | `test_03_wiring.py` |
| A role grants store access | 3 | `test_03_wiring.py` |
| Handler logic | — | Unit |
| An entrypoint end to end | — | End to end |
