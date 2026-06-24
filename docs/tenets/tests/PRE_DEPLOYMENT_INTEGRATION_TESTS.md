# Pre-Deployment Integration Test Tenets

These are the non-negotiable rules for pre-deployment integration tests.

## Table of Contents

- [Integration Tests Verify Components Work Together](#integration-tests-verify-components-work-together)
- [Seven-Layer Testing Model](#seven-layer-testing-model)
- [Test File Organization](#test-file-organization)
- [Layer Marker Implementation](#layer-marker-implementation)
- [Fail Fast with Granular Diagnostics](#fail-fast-with-granular-diagnostics)
- [Cleanup After Capability Tests](#cleanup-after-capability-tests)
- [Fixture Usage](#fixture-usage)
- [Why Terraform Plan is Not a Workflow Step](#why-terraform-plan-is-not-a-workflow-step)
- [Workflow Step Ordering](#workflow-step-ordering)
- [Quick Reference](#quick-reference)
- [Workflow Reference](#workflow-reference)

## Integration Tests Verify Components Work Together

**Integration tests verify that multiple components integrate correctly.**

There are two types of pre-deployment integration tests:

### Local Integration Tests (Contract Tests)

Test that local files/components that must work together are compatible:

- Do test: Template variables in openapi.json match templatefile() vars in Terraform
- Do test: Lambda handler exports match what Terraform references
- Do test: Cross-file configuration consistency
- Do NOT test: Single-file parsing or structure (that's a unit test)

These tests catch contract mismatches between files before deployment.

### AWS Integration Tests (Prerequisite Tests)

Test that AWS resources created by OTHER workflows exist and are configured correctly:

- Do test: Bootstrap resources that must exist before deployment
- Do test: IAM permissions required for deployment
- Do test: External resources referenced by terraform
- Do NOT test: Resources created by the deployment itself

Resources created by the workflow don't exist yet when pre-deployment tests run.

Pre-deployment tests answer: "Can I deploy?"
Post-deployment tests answer: "Did deployment succeed?"

## Seven-Layer Testing Model

Every deployment must pass through seven layers, in order:

| Layer | Purpose | Example |
|-------|---------|---------|
| 1. Contracts | Local files are compatible | openapi.json vars match templatefile() |
| 2. Authentication | Valid credentials exist | Can call sts:GetCallerIdentity |
| 3. Authorization | Permission to inspect resources | Can call s3:HeadBucket |
| 4. State | Terraform state matches AWS reality | Resources to create don't already exist |
| 5. Existence | Resource actually exists | Bucket exists |
| 6. Configuration | Resource configured correctly | IAM role has required policy |
| 7. Capability | Can perform required operations | Can call s3:PutObject |

Each layer catches different failure modes:
- Layer 1 fails → local files are incompatible (contract mismatch)
- Layer 2 fails → credentials invalid or expired
- Layer 3 fails → credentials valid but lack permission to inspect
- Layer 4 fails → state drift - resources exist but not in Terraform state
- Layer 5 fails → have permission to check, but resource doesn't exist
- Layer 6 fails → resource exists but misconfigured
- Layer 7 fails → resource exists and configured, but can't perform operations

## Test File Organization

Tests MUST be organized into exactly seven files by layer:

```
test/{module}/pre_deployment/integration/
├── test_01_contracts.py       # Layer 1: Local files are compatible
├── test_02_authentication.py  # Layer 2: Can authenticate to AWS
├── test_03_authorization.py   # Layer 3: Have permission to inspect prerequisites
├── test_04_state.py           # Layer 4: Terraform state matches AWS reality
├── test_05_existence.py       # Layer 5: Prerequisite resources exist
├── test_06_configuration.py   # Layer 6: Prerequisites configured correctly
└── test_07_capability.py      # Layer 7: Can perform required operations
```

Do NOT organize by resource (test_s3.py, test_iam.py, test_dynamodb.py).
Organizing by resource makes it impossible to know which layer failed.

### Layer 1: Contract Tests (test_01_contracts.py)

Test that local files that must work together are compatible. No AWS calls.

```python
# CORRECT - cross-file contract validation
import re

def test_openapi_template_vars_provided_to_templatefile():
    """Verify all template variables in openapi.json are passed to templatefile."""
    openapi_content = _read_openapi_json()
    tf_content = _read_apigateway_tf()

    # Extract ${VarName} from openapi.json
    template_vars = set(re.findall(r'\$\{(\w+)\}', openapi_content))

    # Extract variables passed to templatefile in apigateway.tf
    templatefile_block = _extract_templatefile_block(tf_content)
    provided_vars = set(re.findall(r'^\s+(\w+)\s+=', templatefile_block, re.MULTILINE))

    missing = template_vars - provided_vars
    assert not missing, f"Template vars in openapi.json missing from templatefile(): {missing}"

def test_lambda_handler_exports_match_terraform_references():
    """Verify Lambda handler exports what Terraform expects."""
    handler_content = _read_handler_py()
    tf_content = _read_lambda_tf()

    # Handler must export what Terraform references
    assert 'def handler(' in handler_content or 'def lambda_handler(' in handler_content
```

```python
# WRONG - this is a unit test (single file)
def test_openapi_has_paths_section():
    """Verify openapi.json has paths."""
    spec = json.load(open('openapi.json'))
    assert 'paths' in spec  # Single file = unit test
```

### Layer 2: Authentication Tests (test_02_authentication.py)

Test ONLY that credentials are valid. No authorization or resource checks.

```python
# CORRECT - authentication only
def test_aws_credentials_valid(sts_client):
    """Verify AWS credentials are valid."""
    response = sts_client.get_caller_identity()
    assert response["Account"] is not None

def test_aws_credentials_not_expired(sts_client):
    """Verify AWS credentials are not expired."""
    # get_caller_identity succeeds = credentials not expired
    response = sts_client.get_caller_identity()
    assert "Arn" in response
```

```python
# WRONG - mixing authentication with authorization
def test_aws_credentials_can_access_s3(s3_client):
    """Verify credentials can access S3."""
    response = s3_client.list_buckets()  # This is authorization, not authentication
    assert response is not None
```

### Layer 3: Authorization Tests (test_03_authorization.py)

Test that credentials have permission to INSPECT prerequisite resources. Not existence, not capability.

```python
# CORRECT - authorization to inspect only
def test_can_describe_iam_role(iam_client, config):
    """Verify permission to inspect IAM role."""
    try:
        iam_client.get_role(RoleName=config["github_actions_role_name"])
    except iam_client.exceptions.NoSuchEntityException:
        pass  # Role doesn't exist, but we have permission to check - that's OK here
    except ClientError as e:
        if e.response["Error"]["Code"] == "AccessDenied":
            pytest.fail("No permission to inspect IAM role")
        raise

def test_can_describe_s3_bucket(s3_client, config):
    """Verify permission to inspect S3 bucket."""
    try:
        s3_client.head_bucket(Bucket=config["state_bucket_name"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "403":
            pytest.fail("No permission to inspect S3 bucket")
        # 404 means bucket doesn't exist - but we have permission to check
        if e.response["Error"]["Code"] != "404":
            raise
```

```python
# WRONG - checking existence in authorization test
def test_can_access_state_bucket(s3_client, config):
    """Verify can access state bucket."""
    response = s3_client.head_bucket(Bucket=config["state_bucket_name"])
    assert response is not None  # This fails if bucket doesn't exist - that's Layer 5
```

### Layer 4: State Tests (test_04_state.py)

Test that Terraform state matches AWS reality. Resources Terraform plans to create should not already exist. Uses `terraform_drift` from `lib/python/`.

```python
# CORRECT - state validation
from terraform_config import TEST_AWS_REGION
from terraform_drift import check_resource_exists, get_planned_creates

def test_no_orphaned_resources():
    """Verify resources to be created don't already exist in AWS."""
    creates = get_planned_creates(TERRAFORM_DIR)

    orphaned = []
    for resource in creates:
        if check_resource_exists(resource["type"], resource["name"], TEST_AWS_REGION):
            orphaned.append(resource)

    if orphaned:
        msg = "\nOrphaned resources detected:\n"
        for r in orphaned:
            msg += f"  - {r['type']}: {r['name']}\n"
            msg += f"    Fix: terraform import {r['address']} {r['name']}\n"
        pytest.fail(msg)
```

**Cold state exception:** For bootstrap workflows, skip state tests if no prior state exists:

```python
@pytest.mark.skipif(
    not _has_existing_state(),
    reason="Cold state - no prior Terraform state to validate against"
)
def test_no_orphaned_resources():
    ...
```

### Layer 5: Existence Tests (test_05_existence.py)

Test that prerequisite resources exist. Assumes authorization passed.

```python
# CORRECT - existence only
def test_github_actions_role_exists(iam_client, config):
    """Verify GitHub Actions IAM role exists."""
    response = iam_client.get_role(RoleName=config["github_actions_role_name"])
    assert response["Role"]["RoleName"] == config["github_actions_role_name"]

def test_state_bucket_exists(s3_client, config):
    """Verify Terraform state bucket exists."""
    response = s3_client.head_bucket(Bucket=config["state_bucket_name"])
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

def test_api_gateway_exists(apigateway_client, config):
    """Verify API Gateway exists."""
    response = apigateway_client.get_rest_api(restApiId=config["api_gateway_id"])
    assert response["id"] == config["api_gateway_id"]
```

```python
# WRONG - mixing existence with configuration
def test_github_actions_role_exists_with_correct_policy(iam_client, config):
    """Verify role exists with correct policy."""
    response = iam_client.get_role(RoleName=config["github_actions_role_name"])
    policies = iam_client.list_attached_role_policies(RoleName=config["github_actions_role_name"])
    assert len(policies["AttachedPolicies"]) > 0  # This is configuration, not existence
```

### Layer 6: Configuration Tests (test_06_configuration.py)

Test that prerequisite resources are configured correctly. Assumes existence passed.

```python
# CORRECT - configuration only
def test_github_actions_role_has_required_policy(iam_client, config):
    """Verify GitHub Actions role has required policy attached."""
    response = iam_client.list_attached_role_policies(
        RoleName=config["github_actions_role_name"]
    )
    policy_arns = [p["PolicyArn"] for p in response["AttachedPolicies"]]
    assert config["required_policy_arn"] in policy_arns

def test_state_bucket_versioning_disabled(s3_client, config):
    """Verify state bucket has versioning disabled."""
    response = s3_client.get_bucket_versioning(Bucket=config["state_bucket_name"])
    status = response.get("Status")
    assert status in ("Suspended", None)

def test_api_gateway_has_github_workflows_webhooks_resource(apigateway_client, config):
    """Verify API Gateway has /v1/github-workflows/webhooks resource."""
    response = apigateway_client.get_resources(restApiId=config["api_gateway_id"])
    paths = [r["path"] for r in response["items"]]
    assert "/v1/github-workflows/webhooks" in paths
```

```python
# WRONG - re-checking existence in configuration test
def test_state_bucket_versioning(s3_client, config):
    """Verify state bucket versioning."""
    s3_client.head_bucket(Bucket=config["state_bucket_name"])  # existence check - unnecessary
    response = s3_client.get_bucket_versioning(Bucket=config["state_bucket_name"])
    assert response.get("Status") == "Enabled"
```

Use fixtures from existence tests. Don't re-verify existence.

### Layer 7: Capability Tests (test_07_capability.py)

Test that you can perform required operations. Assumes configuration passed.

```python
# CORRECT - capability with cleanup
def test_can_write_to_state_bucket(s3_client, config):
    """Verify can write to Terraform state bucket."""
    test_key = f"test/{uuid.uuid4()}.txt"
    try:
        s3_client.put_object(
            Bucket=config["state_bucket_name"],
            Key=test_key,
            Body=b"test"
        )
    finally:
        try:
            s3_client.delete_object(Bucket=config["state_bucket_name"], Key=test_key)
        except ClientError:
            pass

def test_can_assume_deployment_role(sts_client, config):
    """Verify can assume the deployment IAM role."""
    response = sts_client.assume_role(
        RoleArn=config["deployment_role_arn"],
        RoleSessionName="pre-deployment-test"
    )
    assert response["Credentials"]["AccessKeyId"] is not None
```

```python
# WRONG - no cleanup
def test_can_write_to_dynamodb(dynamodb_client, config):
    """Verify can write to DynamoDB."""
    dynamodb_client.put_item(
        TableName=config["table_name"],
        Item={"id": {"S": "test-item"}}
    )
    # Missing cleanup - test artifact remains!
```

**Always clean up in `finally` blocks.**

## Fail Fast with Granular Diagnostics

Cryptic errors like "AccessDenied: Access Denied" are unacceptable.

- Each test must be atomic: one assertion per test
- Tests must run in layer order (authentication before authorization before state before existence)
- When a test fails, the developer must know exactly where the chain broke
- Failure messages must include resource names and expected values

## Cleanup After Capability Tests

If testing write operations, delete test artifacts in `finally` blocks.

```python
def test_can_write(client, resource_id):
    test_id = f"test-{uuid.uuid4()}"
    try:
        client.put_item(Id=test_id, Data="test")
    finally:
        try:
            client.delete_item(Id=test_id)
        except ClientError:
            pass
```

No test artifacts should remain after test execution.

## Fixture Usage

Use fixtures to:
1. Create AWS clients once per module
2. Load configuration from shared config files
3. Cache resource identifiers discovered in earlier layers

```python
# conftest.py
@pytest.fixture(scope="module")
def sts_client(config):
    return boto3.client("sts", region_name=config["aws_region"])

@pytest.fixture(scope="module")
def iam_client(config):
    return boto3.client("iam", region_name=config["aws_region"])

@pytest.fixture(scope="module")
def config():
    """Load configuration from shared config file."""
    with open("etc/config.json") as f:
        return json.load(f)
```

## Why Terraform Plan is Not a Workflow Step

Layer 4 (State) tests replace the need for a separate `terraform plan` step in workflows.

### What Layer 4 Does

- Uses `terraform_drift` library from `lib/python/`
- Runs `terraform plan` internally to detect planned creates
- Checks if those resources already exist in AWS
- Fails if orphaned resources detected (state drift)

### Why This is Better Than a Separate Plan Step

1. **Diagnostics**: Layer 4 tells you exactly which resources have drift
2. **Actionable**: Failure messages include `terraform import` commands
3. **Integrated**: Part of the test pyramid, not a separate manual step
4. **Granular**: Runs after authentication/authorization, so you know credentials work

If layer 4 passes, `terraform apply` will succeed (no unexpected resource conflicts).

## Workflow Step Ordering

Pre-deployment integration tests require a specific position in the workflow:

```
1. Lint (pylint, mypy, yamllint, tflint)
2. Unit tests
3. Pre-deployment integration tests (layers 1-7)
4. Terraform apply
5. Post-deployment integration tests
6. E2E tests
```

### Why This Order

| Step | Depends On | Reason |
|------|------------|--------|
| Lint | Nothing | Fast feedback first |
| Unit tests | Lint | No point running tests if code has errors |
| Pre-deployment integration | Terraform init | Layer 4 needs state access |
| Terraform apply | Pre-deployment passing | Layer 4 validates no drift |
| Post-deployment integration | Resources exist | Can't test what doesn't exist |
| E2E tests | All above | Full system must be deployed |

### Key Points

- Pre-deployment tests run BEFORE `terraform apply`
- Layer 4 requires `terraform init` but NOT `terraform apply`
- If pre-deployment fails, skip apply (fail fast)
- Post-deployment and E2E tests run AFTER successful apply

## Quick Reference

| If you want to test... | Layer | File |
|------------------------|-------|------|
| Template vars match between files | 1. Contracts | test_01_contracts.py |
| Cross-file configuration consistency | 1. Contracts | test_01_contracts.py |
| Lambda exports match Terraform refs | 1. Contracts | test_01_contracts.py |
| AWS credentials valid | 2. Authentication | test_02_authentication.py |
| Can call sts:GetCallerIdentity | 2. Authentication | test_02_authentication.py |
| Can describe IAM role | 3. Authorization | test_03_authorization.py |
| Can head S3 bucket | 3. Authorization | test_03_authorization.py |
| Terraform state matches reality | 4. State | test_04_state.py |
| No orphaned resources | 4. State | test_04_state.py |
| IAM role exists | 5. Existence | test_05_existence.py |
| S3 bucket exists | 5. Existence | test_05_existence.py |
| API Gateway exists | 5. Existence | test_05_existence.py |
| Role has policy attached | 6. Configuration | test_06_configuration.py |
| Bucket has versioning | 6. Configuration | test_06_configuration.py |
| API has required resource | 6. Configuration | test_06_configuration.py |
| Can write to S3 | 7. Capability | test_07_capability.py |
| Can assume role | 7. Capability | test_07_capability.py |
| Can invoke Lambda | 7. Capability | test_07_capability.py |

## Workflow Reference

| Workflow | Prerequisites to Test | NOT Test (created by this workflow) |
|----------|----------------------|-------------------------------------|
| `github_workflows_webhooks` | IAM role from bootstrap, API Gateway from api_common_routing | SQS queues, DynamoDB tables, Lambda functions |
| `api_common_routing` | S3 buckets from bootstrap, Route53 zone | API Gateway, Lambda functions |
| `api_operational_health` | API Gateway from api_common_routing | Lambda function |
| `image_for_ecs_runners` | ECR repository from bootstrap | Docker image |
