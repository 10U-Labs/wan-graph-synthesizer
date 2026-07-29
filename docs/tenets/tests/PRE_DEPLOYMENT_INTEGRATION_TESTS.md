# Pre-Deployment Integration Test Tenets

These are the non-negotiable rules for pre-deployment integration tests.
They live under a stack's `pre_deployment/integration/` directory and run
before the `reconciliation` job applies anything.

Pre-deployment tests answer one question: can this stack be reconciled?
Post-deployment tests answer the other: did reconciliation succeed?

## Table of Contents

- [Two Kinds of Test](#two-kinds-of-test)
- [The Four-Layer Model](#the-four-layer-model)
- [Test File Organization](#test-file-organization)
- [Layer 1, Contracts](#layer-1-contracts)
- [Layer 2, Authentication](#layer-2-authentication)
- [Layer 3, Authorization](#layer-3-authorization)
- [Layer 4, State](#layer-4-state)
- [Behavioural Integration Modules](#behavioural-integration-modules)
- [Read Only, Never Write](#read-only-never-write)
- [Fail Fast with Granular Diagnostics](#fail-fast-with-granular-diagnostics)
- [Fixture Usage](#fixture-usage)
- [Why There Is No Plan Step](#why-there-is-no-plan-step)
- [Position in the Workflow](#position-in-the-workflow)
- [Quick Reference](#quick-reference)
- [Stack Reference](#stack-reference)

## Two Kinds of Test

### Local contract tests

Verify that files which must agree with each other do agree. No AWS.

- Do test: every `module.common.*` reference resolves to a declared
  output of the shared common module.
- Do test: the stack's `outputs.tf` is wired to the resource it claims.
- Do test: remote state references point at the stack that owns them.
- Do NOT test: the structure of a single file on its own. Parsing one
  file is a unit test.

### AWS prerequisite tests

Verify that the credentials and the state this reconciliation depends on
are sound.

- Do test: credentials exist and resolve to an account.
- Do test: those credentials may inspect the shared state bucket.
- Do test: nothing the stack would create already exists unmanaged.
- Do NOT test: resources this stack is about to create. They do not
  exist yet, and asserting on them belongs to the post-deployment tier.

## The Four-Layer Model

Every stack passes through four layers, in order.

| Layer | Question |
| --- | --- |
| 1. Contracts | Do the local files agree? |
| 2. Authentication | Are the credentials valid? |
| 3. Authorization | May they inspect what is needed? |
| 4. State | Does declared state match AWS? |

Each layer isolates a different failure.

- Layer 1 fails: two files disagree, and no deployment would fix it.
- Layer 2 fails: credentials are missing or expired.
- Layer 3 fails: credentials are valid but lack permission to look.
- Layer 4 fails: a resource exists in AWS outside of state, so the apply
  would collide with it.

Existence, configuration and wiring are deliberately absent here. In this
repository each workflow owns exactly one stack, so the resources those
layers would inspect are the ones this reconciliation creates. They are
covered in [POST_DEPLOYMENT_INTEGRATION_TESTS.md](POST_DEPLOYMENT_INTEGRATION_TESTS.md),
and a dependency on another stack is asserted against that stack's
declared outputs in layer 1 rather than by calling AWS.

## Test File Organization

Layer tests are organised into exactly four files, one per layer.

```text
test/api/endpoints/<endpoint>/pre_deployment/integration/
├── conftest.py                # Re-exports the boto3 fixtures used
├── test_01_contracts.py       # Layer 1
├── test_02_authentication.py  # Layer 2
├── test_03_authorization.py   # Layer 3
└── test_04_state.py           # Layer 4
```

Do not organise by resource. A `test_s3.py` makes it impossible to see
which layer broke, which is the whole point of the numbering.

## Layer 1, Contracts

Cross-file consistency, asserted against the declaration rather than a
copied literal. This is the only layer most stacks write by hand, and the
only one that grows when a stack gains a coupling.

```python
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values


def test_locals_reference_only_declared_common_outputs() -> None:
    """Every ``module.common.*`` reference resolves to a declared output."""
    refs = set(re.findall(r"module\.common\.(\w+)", _stack_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_lambda_arn_output_references_the_declared_handler() -> None:
    """The ``lambda_function_arn`` output is wired to the declared handler."""
    outputs = output_values(TENANTS_DIR / "outputs.tf")
    assert "aws_lambda_function.handler" in str(outputs["lambda_function_arn"])
```

A single-file assertion is not a contract test:

```python
def test_openapi_has_paths_section() -> None:
    """The spec declares a paths object."""
    assert "paths" in json.load(open("openapi.json"))
```

That reads one file, so it belongs in `pre_deployment/unit/`.

## Layer 2, Authentication

Credentials only. Nothing about permissions and nothing about resources.

Every stack's authentication layer is identical, so no stack writes it.
Instantiate the shared class instead, which keeps `jscpd` quiet and keeps
the coverage the same everywhere.

```python
"""Layer 2 (authentication): valid AWS credentials before reconciling."""
from __future__ import annotations

from test_fixtures.integration import create_simple_layer1_authentication_tests

TestAWSAuthentication = create_simple_layer1_authentication_tests()
```

The factory names in `test_fixtures.integration` carry an older
numbering, one lower than the file numbering. The file names are the
authoritative layer numbers.

Calling `s3:ListBuckets` here would be an authorization test, not an
authentication one, and belongs one layer down.

## Layer 3, Authorization

Permission to inspect, not the existence of what is inspected.

```python
"""Layer 3 (authorization): permission to inspect the shared state bucket."""
from __future__ import annotations

from test_fixtures.integration import create_layer2_s3_authorization_tests

TestS3Authorization = create_layer2_s3_authorization_tests()
```

The distinction the shared helper encodes is worth restating: a 403 fails
the test because permission is missing, while a 404 passes it because the
call was allowed and the resource simply is not there. Absence is layer
5's business, and layer 5 lives in the post-deployment tier.

## Layer 4, State

Run `tofu plan` and confirm nothing it would create already exists in AWS
outside of state.

```python
from repo_utils import REPO_ROOT
from test_terraform_drift import find_orphaned_resources, get_state_resources

TENANTS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants"


def _has_existing_state() -> bool:
    """Report whether the stack already has resources tracked in state."""
    return bool(get_state_resources(TENANTS_DIR))


@pytest.mark.skipif(
    not _has_existing_state(),
    reason="Cold state - no prior OpenTofu state to validate against",
)
def test_no_orphaned_resources() -> None:
    """No resource the stack would create already exists unmanaged in AWS."""
    assert not find_orphaned_resources(TENANTS_DIR)
```

The cold-state skip is required, not optional. A stack that has never
been reconciled has no state to compare against, and without the skip its
first run fails on a condition that cannot be true yet.

This layer needs `tofu init` to have run in the workflow, and nothing
more. It never applies.

## Behavioural Integration Modules

A stack whose code is pure Python has a second kind of local integration
test: several modules exercised against each other, with no AWS and no
Terraform. The synthesizer stack has one.

```text
test/api/endpoints/tenants/wan/post/pre_deployment/integration/
├── test_01_contracts.py
└── test_synthesize_two_tier.py
```

These are named for the behaviour they exercise rather than a layer
number, because they are not part of the ordered chain. Keep the
distinction from a unit test sharp: if the test would still pass with
every collaborating module replaced by a literal, it is a unit test and
belongs in `pre_deployment/unit/`.

## Read Only, Never Write

Pre-deployment tests inspect. They never create, mutate or delete an AWS
resource, and they never leave an artifact behind.

A write here would defeat layer 4, which exists precisely to prove that
nothing unmanaged is sitting where the apply is about to land. The tier
therefore has no cleanup rules, because it has nothing to clean up.

## Fail Fast with Granular Diagnostics

An error reading `AccessDenied: Access Denied` is not acceptable
diagnostics.

- One assert per test, enforced by `assert-one-assert-per-pytest`.
- Layers run in numeric order, so the first failure names the stage.
- A failure message carries the resource name and the expected value.
- A helper that fails deliberately, such as the 403 branch of the
  `s3:HeadBucket` check, calls `pytest.fail` with the bucket name in the
  message rather than letting a bare exception surface.

## Fixture Usage

The tier's `conftest.py` re-exports only the boto3 fixtures the tier
uses. It does not construct them.

```python
"""Boto3 fixtures for the tenants pre-deployment integration tier."""
from __future__ import annotations

from test_fixtures.aws import s3_client, state_bucket_name, sts_client

__all__ = ["s3_client", "state_bucket_name", "sts_client"]
```

Names derived from the stack's declared configuration, such as
`function_name` and `role_name`, come from the stack's own `conftest.py`
one level up and are shared with every other tier.

## Why There Is No Plan Step

Layer 4 replaces a separate `tofu plan` workflow step.

- It runs the plan internally, through `test_terraform_drift`.
- It then checks AWS for each resource the plan would create.
- It fails naming the specific resources that already exist.

A bare plan step would print a diff nobody gates on. Layer 4 gates, and
it reports the drift in the same place as every other test failure. If
layer 4 passes, the apply will not collide with an unmanaged resource.

## Position in the Workflow

```text
static-analysis
  └── unit-tests
        └── pre-deployment-integration-tests
              └── reconciliation
                    └── post-deployment-integration-tests
```

The job itself does three things before pytest: it assumes the OIDC role,
sets up OpenTofu, and initialises the stack.

```yaml
- name: Initialize the stack for state inspection
  run: tofu -chdir=src/api/endpoints/tenants init -input=false
- name: Run pre-deployment integration tests
  run: >-
    PYTHONPATH=.:lib/python
    python3 -m pytest
    test/api/endpoints/tenants/pre_deployment/integration/
    --import-mode=importlib --confcutdir=test
    --verbose
```

The job is gated on `github.ref == 'refs/heads/main'`, because it needs
AWS credentials. Static analysis and unit tests are not.

## Quick Reference

| To test | Layer | File |
| --- | --- | --- |
| Cross-file agreement | 1 | `test_01_contracts.py` |
| Outputs wired to a resource | 1 | `test_01_contracts.py` |
| Remote state references | 1 | `test_01_contracts.py` |
| Credentials resolve | 2 | `test_02_authentication.py` |
| Permission to inspect | 3 | `test_03_authorization.py` |
| No unmanaged resources | 4 | `test_04_state.py` |
| A live resource's settings | — | Post-deployment |
| A module against a module | — | Behavioural module |

## Stack Reference

Every endpoint stack reads the common `storage` and `routing` state, so
each one's layer 1 asserts that coupling. What follows is what each stack
may treat as a prerequisite, and what it must leave to its own
post-deployment tier.

| Stack | Prerequisites |
| --- | --- |
| `api/common/storage` | The shared state bucket |
| `api/common/routing` | The shared common module |
| `api/endpoints/carriers` | Storage and routing state |
| `api/endpoints/data-centers` | Storage and routing state |
| `api/endpoints/providers` | Storage and routing state |
| `api/endpoints/tenants` | Storage and routing state |
| `api/endpoints/tenants/wan` | The tenants stack |
| `api/endpoints/tenants/wan/post` | The common module |

The `tenants/wan` dispatcher invokes the synthesizer by a name derived
from the common module rather than by a shared resource reference, so
neither stack is a prerequisite of the other's apply. Their coupling is
asserted in layer 1 on both sides. `.github/workflows/SEQUENCE.md` holds
the full picture.
