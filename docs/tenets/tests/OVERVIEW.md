# Test Architecture Overview

This document explains the test infrastructure, where to put common code, and what reusable utilities exist.

## Table of Contents

- [Test Hierarchy](#test-hierarchy)
- [Directory Scope](#directory-scope)
- [Reusable Utilities in lib/python/](#reusable-utilities-in-libpython)
  - [test_fixtures/](#test_fixtures)
  - [terraform_config/](#terraform_config)
  - [terraform_drift/](#terraform_drift)
  - [naming_conventions/](#naming_conventions)
  - [boto_mocks/](#boto_mocks)
  - [event_factories/](#event_factories)
  - [lambda_response/](#lambda_response)
  - [module_utils/](#module_utils)
- [Check Before You Create](#check-before-you-create)
- [Layer Marker System](#layer-marker-system)
- [Static Analysis in Workflows](#static-analysis-in-workflows)

## Test Hierarchy

Tests follow a cascading conftest.py pattern. Each level inherits from parents and adds specifics.

```
test/
├── conftest.py                              # Level 0: Path setup (lib/python)
├── api/
│   ├── conftest.py                          # Level 1: API fixtures, terraform utilities
│   └── backend/
│       ├── conftest.py                      # Level 2: Backend config parsing
│       ├── pre_deployment/
│       │   ├── unit/conftest.py             # Level 3: Lambda mocks, event factories
│       │   └── integration/conftest.py      # Level 3: Layer markers, bootstrap fixtures
│       └── post_deployment/
│           ├── integration/conftest.py      # Level 3: AWS clients, layer markers
│           └── e2e/conftest.py              # Level 3: Endpoint deployment checks
```

### Where to Put Common Things

| Scope | Location | Examples |
|-------|----------|----------|
| All tests | `test/conftest.py` | Path setup (already done) |
| All API tests | `test/api/conftest.py` | Terraform utilities, runner labels |
| All backend tests | `test/api/backend/conftest.py` | Config parsing from tfvars/locals |
| Pre-deployment unit | `test/.../pre_deployment/unit/conftest.py` | Lambda mocks, event factories |
| Pre-deployment integration | `test/.../pre_deployment/integration/conftest.py` | Layer markers, bootstrap fixtures |
| Post-deployment integration | `test/.../post_deployment/integration/conftest.py` | Layer markers, AWS service clients |

**Rule:** Put fixtures at the highest level where they apply. Don't duplicate.

## Directory Scope

Shared directories are for codebase-wide utilities, not module-specific code.

| Directory | Scope | Example Contents |
|-----------|-------|------------------|
| `lib/python/` | Entire codebase | `boto_mocks/`, `terraform_config/`, `test_fixtures/aws.py` |
| `test/` root | All tests | `conftest.py` (path setup), codebase-wide test utilities |
| `test/<module>/` | Module-specific | `test/workflowctl/conftest.py`, inline `SAMPLE_GRAPH` constants |

**Key principle:** If a fixture or utility is only used by one module's tests, keep it within that module's test directory. Don't pollute shared directories with module-specific code.

Examples:
- ✅ `lib/python/boto_mocks/` — Used by API, Lambda, and infrastructure tests across the codebase
- ✅ `test/api/conftest.py` — Terraform utilities used by all API endpoint tests
- ✅ `test/workflowctl/conftest.py` — Fixtures specific to workflowctl tests
- ❌ `lib/python/test_fixtures/workflowctl.py` — Wrong: workflowctl-specific code in codebase-wide lib/
- ❌ `test/workflowctl_fixtures.py` — Wrong: workflowctl-specific code at test/ root level

## Reusable Utilities in lib/python/

Before creating new fixtures, check if they exist in `lib/python/`. Import via `pytest_plugins` or direct import.

### test_fixtures/

AWS fixtures ready to use via pytest plugin:

```python
# In conftest.py
pytest_plugins = ['test_fixtures.aws']

# Provides these fixtures:
# - shared_config: Parsed shared Terraform module config
# - aws_region: AWS region from config
# - state_bucket_name: Terraform state bucket
# - sts_client, iam_client, s3_client, ssm_client, kms_client, ecr_client
# - caller_identity, current_role_arn, current_role_name
```

### terraform_config/

Parse Terraform configuration as single source of truth:

```python
from terraform_config import (
    get_shared_config,        # Combined locals + outputs + handlers
    parse_locals,             # Parse locals.tf
    parse_outputs,            # Parse outputs.tf
    get_tfvars_values,        # Parse terraform.tfvars
    get_resource_prefix,      # Resource naming prefix
    extract_lambda_function_names,  # Lambda names from .tf files
    TEST_AWS_REGION,          # Standard region for test mocks
)
```

### terraform_drift/

Detect orphaned resources (resources in AWS but not in Terraform state):

```python
from terraform_drift import check_resource_exists, get_planned_creates
from terraform_drift.test_helpers import create_orphaned_resource_tests

# Generate test class for orphaned resource detection
TestOrphanedResources = create_orphaned_resource_tests(
    terraform_dir=TERRAFORM_DIR,
    region="us-east-2",
)
```

### naming_conventions/

Validate AWS resource names follow PascalCase:

```python
from naming_conventions import is_pascalcase, validate_name
from naming_conventions.test_helpers import (
    create_lambda_function_tests,
    create_iam_role_tests,
    create_sqs_queue_tests,
)

# Generate parametrized naming tests
TestLambdaNaming = create_lambda_function_tests(lambda_names)
```

### boto_mocks/

Factory functions for boto3 mocks in unit tests:

```python
from boto_mocks import (
    create_client_error,      # Create ClientError for error testing
    create_boto_client_mock,  # Create flexible boto3.client mock
    create_mock_lambda_with_mappings,
    create_mock_sns_publish_error,
)
```

### event_factories/

Create test Lambda event payloads:

```python
from event_factories import (
    create_workflow_job_event,     # GitHub workflow_job webhook
    create_sqs_event,              # SQS trigger event
    create_dlq_message,            # DLQ message format
    create_circuit_breaker_closed_state,
    create_circuit_breaker_open_state,
)
```

### lambda_response/

Assert Lambda response structure:

```python
from lambda_response import (
    parse_response_body,
    assert_response_status,
    assert_json_content_type,
    assert_cors_headers,
)
```

### module_utils/

Reset module state between tests (for Lambda handlers with cached clients):

```python
from module_utils import reset_module_state

def test_something(handler_module):
    reset_module_state(handler_module, boto_client=None, cache={})
```

## Check Before You Create

Before writing new fixtures or utilities:

1. **Check parent conftest files** - The fixture may already exist at a higher level
2. **Check lib/python/** - Reusable utilities may already solve your problem
3. **Check test_fixtures.aws** - Common AWS fixtures are already available

If your fixture is useful beyond your specific test file:
- Put it in the appropriate conftest.py level
- Or add it to lib/python/ if it's broadly reusable

## Static Analysis in Workflows

Linting and type checking must run separately for source and test code.

### Required Workflow Steps

| Step Name | Target |
|-----------|--------|
| `Run pylint on source` | `lib/python/` and `src/.../lambdas/` |
| `Run pylint on tests` | `lib/python/`, parent conftest files, and `test/.../endpoint/` (with `PYTHONPATH=lib/python`) |
| `Run mypy on source` | `lib/python/` and `src/.../lambdas/` |
| `Run mypy on tests` | `lib/python/`, parent conftest files, and `test/.../endpoint/` (with `MYPYPATH=lib/python`) |

### Why Separate Steps?

1. **Different configurations** - Tests need `PYTHONPATH`/`MYPYPATH` set to resolve `lib/python/` imports
2. **Clear failure attribution** - When a step fails, you immediately know if it's source or test code
3. **Consistent naming** - All workflows use the same step names for easy identification

### Example

```yaml
- name: Run pylint on source
  run: |
    python3 -m pylint \
      lib/python/ src/api/endpoints/example/lambdas/ \
      --fail-on=C,R,W \
      --fail-under=10.0
- name: Run pylint on tests
  run: |
    PYTHONPATH=lib/python python3 -m pylint \
      lib/python/ test/conftest.py test/api/conftest.py \
      test/api/endpoints/conftest.py test/api/endpoints/example/ \
      --fail-on=C,R,W \
      --fail-under=10.0
- name: Run mypy on source
  run: |
    python3 -m mypy \
      lib/python/ src/api/endpoints/example/lambdas/
- name: Run mypy on tests
  run: |
    MYPYPATH=lib/python python3 -m mypy \
      lib/python/ test/conftest.py test/api/conftest.py \
      test/api/endpoints/conftest.py test/api/endpoints/example/
```
