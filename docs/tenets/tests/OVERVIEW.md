# Test Architecture Overview

This document explains the test infrastructure of this repository: the
tiers a change must cover, where common code goes, and which reusable
utilities already exist.

The repository is Python on AWS Lambda, with the infrastructure declared
in OpenTofu and reconciled by GitHub Actions. Every test is pytest.
There is no JavaScript test suite and no test runner other than pytest.

## Table of Contents

- [Test Tiers](#test-tiers)
- [Directory Layout](#directory-layout)
- [Where Shared Code Goes](#where-shared-code-goes)
- [Reusable Utilities](#reusable-utilities)
- [Check Before You Create](#check-before-you-create)
- [Static Analysis in Workflows](#static-analysis-in-workflows)
- [Workflow Job Order](#workflow-job-order)

## Test Tiers

A stack's tests live under `test/` in a directory mirroring its path
under `src/`, split into tiers by when they can run.

| Tier | Directory under the stack's test root |
| --- | --- |
| Unit | `pre_deployment/unit/` |
| Pre-deployment integration | `pre_deployment/integration/` |
| Post-deployment integration | `post_deployment/integration/` |

Each tier answers a different question.

- Unit: is this module correct on its own? Nothing external is touched.
- Pre-deployment integration: can this stack be reconciled? Local files
  agree with each other, credentials work, and declared state matches
  AWS reality.
- Post-deployment integration: did reconciliation succeed? The live
  resources exist, are configured as declared, and are wired together.

The end-to-end tier is separate. It exists only for the seed script, at
`test/scripts/seed/e2e/`, and runs the real entrypoint as a subprocess
against a localhost stub API. See
[E2E_TESTS.md](E2E_TESTS.md).

Unit tests alone are never sufficient. Add coverage at every tier the
change touches.

## Directory Layout

Tests follow a cascading `conftest.py` pattern. Each level inherits from
its parents and adds what only it needs.

```text
test/
├── conftest.py                     # Import paths: repo, lib, src, test
├── fixtures.py                     # Synthesizer graph fixtures
├── api/
│   ├── common/
│   │   ├── routing/
│   │   │   ├── conftest.py         # Parsed routing stack config
│   │   │   ├── pre_deployment/
│   │   │   │   ├── unit/
│   │   │   │   └── integration/
│   │   │   └── post_deployment/
│   │   │       └── integration/
│   │   └── storage/
│   └── endpoints/
│       ├── carriers/
│       ├── data-centers/
│       ├── providers/
│       └── tenants/
│           ├── conftest.py         # Lambda and role names for the stack
│           ├── pre_deployment/
│           ├── post_deployment/
│           └── wan/
│               └── post/           # The synthesizer stack
└── scripts/
    └── seed/
        ├── unit/
        ├── integration/
        └── e2e/
```

There is no `test/api/conftest.py` and no `test/api/endpoints/`
`conftest.py`. Shared setup lives either at `test/conftest.py` or in
`lib/python/`, and stack-specific fixtures live in the stack's own
`conftest.py`.

`test/conftest.py` does one job: it puts the repository root,
`lib/python/`, `src/` and `test/` on `sys.path`. Workflows set
`PYTHONPATH` to the same directories, so a test module imports
`synthesizer.backbone` or `test_terraform_config` directly.

## Where Shared Code Goes

Put a fixture at the highest level where it applies, and no higher.

| Scope | Location |
| --- | --- |
| Every test in the repository | `test/conftest.py` |
| Every codebase user | `lib/python/` |
| Synthesizer inputs | `test/fixtures.py` |
| One stack, every tier | `test/.../<stack>/conftest.py` |
| One stack, one tier | `test/.../<tier>/conftest.py` |

A stack's `conftest.py` parses that stack's declared OpenTofu config and
exposes the derived names (`function_name`, `role_name`) that every tier
needs. A tier's `conftest.py` re-exports the boto3 client fixtures the
tier uses and derives anything fetched once per module, such as the live
Lambda configuration block shared by the three post-deployment layers.

Do not put stack-specific code in `lib/python/`, and do not put
codebase-wide code in a stack's test directory.

## Reusable Utilities

Before writing a fixture, check whether `lib/python/` already has it.
Every module there is importable from tests because `test/conftest.py`
and the workflows both put `lib/python/` on the path.

### repo_utils

Locate the repository root without relative-path arithmetic.

```python
from repo_utils import REPO_ROOT

TENANTS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants"
```

### test_fixtures.aws

Session-scoped boto3 clients and the shared configuration they need.

```python
from test_fixtures.aws import (
    config,                # Parsed shared common outputs
    state_bucket_name,     # Shared OpenTofu state bucket
    sts_client,
    iam_client,
    s3_client,
    lambda_client,
    apigateway_client,
    logs_client,
    dynamodb_client,
    sqs_client,
    sns_client,
    events_client,
    ecr_client,
    iam_role_exists,       # Helper: does a role exist?
    get_log_group_info,    # Helper: existence and retention
)
```

A tier `conftest.py` re-exports only the clients that tier uses:

```python
from test_fixtures.aws import iam_client, lambda_client, logs_client

__all__ = ["iam_client", "lambda_client", "logs_client"]
```

### test_fixtures.integration

Generated test classes for the pre-deployment layers that are identical
across every stack, so no stack hand-writes them.

```python
from test_fixtures.integration import (
    check_s3_head_bucket_permission,
    create_simple_layer1_authentication_tests,
    create_layer2_s3_authorization_tests,
)

TestAWSAuthentication = create_simple_layer1_authentication_tests()
```

### test_terraform_config

Parse declared OpenTofu configuration as the single source of truth, so
a test asserts against the declaration rather than a copied literal.

```python
from test_terraform_config import (
    COMMON_OUTPUTS_FILE,
    load_tf,               # Parse one .tf file
    find_resource,         # Locate a resource block
    output_values,         # Parse an outputs.tf
    common_outputs,        # Parsed shared common outputs
    lambda_handler_names,  # Derived Lambda function names
)
```

### test_terraform_drift

Detect resources that exist in AWS but not in state.

```python
from test_terraform_drift import (
    check_resource_exists,
    get_planned_creates,
    get_state_resources,
    is_resource_in_state,
    find_orphaned_resources,
)
```

### test_naming_conventions

Validate AWS resource names and API path segments.

```python
from test_naming_conventions import (
    is_pascalcase,
    validate_name,
    find_violations,
    is_kebabcase,
    validate_kebab_name,
)
```

### test_s3_store_mock

In-memory doubles for the AWS services a handler calls, for unit tests.

```python
from test_s3_store_mock import (
    NoSuchKey,
    fake_s3,
    fake_ecs,
    fake_scheduler,
    fake_lambda,
)
```

### test_http_doubles

HTTP doubles for code that speaks to an API rather than to boto3.

```python
from test_http_doubles import (
    EMPTY_LISTING,
    FakeResponse,
    UrlopenRecorder,
    CallRecorder,
    StubApi,          # A real localhost server recording requests
)
```

### test_handler_contracts

Shared contract suites for the endpoint handlers, which are the same
reader and writer shape repeated per collection.

```python
from test_handler_contracts import (
    load_handler,
    write_clients,
    write_event,
    ReaderContract,
    WriterContract,
    RegionsContract,
)
```

### test_module_utils

Load a Lambda handler module by path, since handlers are not packages.

```python
from test_module_utils import create_lambda_loader, load_module_from_path
```

## Check Before You Create

Before writing a new fixture or helper:

1. Check the parent `conftest.py` files. The fixture may already exist
   at a higher level.
2. Check `lib/python/`. A utility may already solve the problem.
3. Check `test/fixtures.py` if the input is a graph, vertex or design.

Duplication is not merely discouraged here, it fails the build: every
workflow runs `jscpd` at a zero-tolerance threshold over both source and
tests. A copied fixture is a red run, not a review comment.

## Static Analysis in Workflows

Linting and type checking run separately for source and for tests,
because the two need different import paths and because a failure should
name which side broke.

| Step name | Target |
| --- | --- |
| `Run pylint on source` | Lambda sources and `lib/python/` |
| `Run mypy on source` | Lambda sources and `lib/python/` |
| `Detect copy-paste in source` | The same source set |
| `Run pylint on tests` | The stack's conftest and tiers |
| `Run mypy on tests` | The same test set |
| `Detect copy-paste in tests` | The stack's test directory |

Four gates run before those, and they are the reason no local linter
configuration exists anywhere in the tree.

| Step name | What it forbids |
| --- | --- |
| `Lint YAML` | yamllint findings in the workflow |
| `Assert no inline directives` | Per-line linter suppressions |
| `Assert no linter config files` | Repository-level rule overrides |
| `Assert one assert per pytest` | More than one assert per test |

The last of those makes the atomicity rule in
[UNIT_TESTS.md](UNIT_TESTS.md) mechanical rather than advisory.

An example, from `api_endpoint_tenants.yml`:

```yaml
- name: Run pylint on source
  run: >-
    PYTHONPATH=lib/python:src/api/endpoints/tenants/lambdas
    python3 -m pylint
    src/api/endpoints/tenants/lambdas/handler.py
    lib/python/test_terraform_config
    lib/python/test_terraform_drift
    lib/python/test_fixtures
    --fail-on=C,R,W --fail-under=10.0
- name: Run mypy on source
  run: >-
    MYPYPATH=lib/python:src/api/endpoints/tenants/lambdas
    python3 -m mypy --strict --explicit-package-bases
    --ignore-missing-imports
    src/api/endpoints/tenants/lambdas/handler.py
    lib/python/test_terraform_config
    lib/python/test_terraform_drift
    lib/python/test_fixtures
```

Note `--fail-on=C,R,W` and `--fail-under=10.0` for pylint, and `--strict`
for mypy. There is no tolerance band: a convention warning fails the run.

## Workflow Job Order

Each stack has one workflow, path-filtered to that stack. Its jobs run in
a fixed order, and each needs the one before it.

```text
static-analysis
  └── unit-tests
        └── pre-deployment-integration-tests
              └── reconciliation
                    └── post-deployment-integration-tests
```

The reasoning behind the order:

- `static-analysis` needs nothing, so it gives the fastest feedback.
- `unit-tests` runs behind it, because there is no point testing code
  that does not lint. It carries the coverage gate.
- `pre-deployment-integration-tests` runs `tofu init` first, because the
  state layer inspects state. It does not apply anything.
- `reconciliation` runs `tofu apply`, and only after the pre-deployment
  tier has confirmed nothing it would create already exists.
- `post-deployment-integration-tests` runs last, because there are no
  live resources to inspect until reconciliation has finished.

Reconciliation and the two integration tiers are gated on
`github.ref == 'refs/heads/main'`. Static analysis and unit tests are
not, so they run on every push.

A push can trigger several path-filtered workflows at once. The change is
done when each workflow that fired is green, not when the first one is.
