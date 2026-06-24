# Post-Deployment Integration Test Tenets

These are the non-negotiable rules for post-deployment integration tests.

## Table of Contents

- [Only Test This Deployment's Resources](#only-test-this-deployments-resources)
- [Three-Layer Testing Model](#three-layer-testing-model)
- [Test File Organization](#test-file-organization)
- [Layer Marker Implementation](#layer-marker-implementation)
- [Fail Fast with Granular Diagnostics](#fail-fast-with-granular-diagnostics)
- [Boundary with E2E Tests](#boundary-with-e2e-tests)
- [No Cleanup Required](#no-cleanup-required)
- [Fixture Usage](#fixture-usage)
- [Quick Reference](#quick-reference)

## Only Test This Deployment's Resources

**Post-deployment tests ONLY test resources created by THIS workflow.**

- Do test: Resources created by terraform apply
- Do test: Resource configuration matches expected values
- Do test: Component wiring (triggers, layers, IAM cross-service)
- Do NOT test: Full user journeys (those are e2e tests)
- Do NOT test: Resources created by other workflows
- Do NOT test: Application logic or business rules (unit tests)

Post-deployment tests answer: "Did my deployment succeed?"
E2E tests answer: "Does the user journey work?"

## Three-Layer Testing Model

Every deployed resource must be tested through three layers, in order:

| Layer | Purpose | Example |
|-------|---------|---------|
| 1. Existence | Resource was created | Lambda function exists |
| 2. Configuration | Resource configured correctly | SQS queue has 14-day retention |
| 3. Wiring | Components connected properly | Lambda has Layer attached, SQS triggers Lambda |

Each layer catches different failure modes:
- Layer 1 fails → terraform didn't create the resource
- Layer 2 fails → resource exists but misconfigured
- Layer 3 fails → resources exist and configured, but not connected

## Test File Organization

Tests MUST be organized into exactly three files by layer:

```
test/api/endpoints/{endpoint}/post_deployment/integration/
├── test_01_existence.py       # Layer 1: All resources exist
├── test_02_configuration.py   # Layer 2: All resources configured correctly
└── test_03_wiring.py          # Layer 3: All components connected properly
```

Do NOT organize by resource (test_lambda.py, test_sqs.py, test_dynamodb.py).
Organizing by resource makes it impossible to know which layer failed.

### Layer 1: Existence Tests (test_01_existence.py)

Test ONLY that resources exist. No configuration checks.

```python
# CORRECT - existence only
def test_webhook_handler_lambda_exists(lambda_client, config):
    """Verify TenULabsWebhookHandler Lambda exists."""
    response = lambda_client.get_function(FunctionName="TenULabsWebhookHandler")
    assert response["Configuration"]["FunctionName"] == "TenULabsWebhookHandler"

def test_runners_layer_exists(lambda_client):
    """Verify TenULabsRunnersLayer exists."""
    response = lambda_client.list_layer_versions(LayerName="TenULabsRunnersLayer")
    assert len(response["LayerVersions"]) > 0

def test_job_queue_exists(sqs_client, config):
    """Verify job queue exists."""
    queue_url = sqs_client.get_queue_url(QueueName="TenULabsRunnersJobQueue")
    assert queue_url["QueueUrl"] is not None

def test_idempotency_table_exists(dynamodb_client):
    """Verify idempotency DynamoDB table exists."""
    response = dynamodb_client.describe_table(TableName="TenULabsRunnersIdempotency")
    assert response["Table"]["TableName"] == "TenULabsRunnersIdempotency"
```

```python
# WRONG - mixing existence with configuration
def test_webhook_handler_lambda_exists_with_correct_timeout(lambda_client):
    response = lambda_client.get_function(FunctionName="TenULabsWebhookHandler")
    assert response["Configuration"]["Timeout"] == 30  # This is configuration, not existence
```

### Layer 2: Configuration Tests (test_02_configuration.py)

Test that resources have correct settings. Assumes existence tests passed.

```python
# CORRECT - configuration only
def test_job_queue_has_14_day_retention(sqs_client, job_queue_url):
    """Verify job queue retains messages for 14 days."""
    attrs = sqs_client.get_queue_attributes(
        QueueUrl=job_queue_url,
        AttributeNames=["MessageRetentionPeriod"]
    )
    assert attrs["Attributes"]["MessageRetentionPeriod"] == "1209600"

def test_webhook_handler_has_30_second_timeout(lambda_client):
    """Verify webhook handler timeout is 30 seconds."""
    response = lambda_client.get_function(FunctionName="TenULabsWebhookHandler")
    assert response["Configuration"]["Timeout"] == 30

def test_idempotency_table_has_ttl_enabled(dynamodb_client):
    """Verify idempotency table has TTL on expiration_time."""
    response = dynamodb_client.describe_time_to_live(
        TableName="TenULabsRunnersIdempotency"
    )
    assert response["TimeToLiveDescription"]["TimeToLiveStatus"] == "ENABLED"
    assert response["TimeToLiveDescription"]["AttributeName"] == "expiration_time"
```

```python
# WRONG - checking existence in configuration test
def test_job_queue_retention(sqs_client):
    queue_url = sqs_client.get_queue_url(QueueName="TenULabsRunnersJobQueue")  # existence check
    attrs = sqs_client.get_queue_attributes(...)
    assert attrs["Attributes"]["MessageRetentionPeriod"] == "1209600"
```

Use fixtures to get resource identifiers. Don't re-check existence.

### Layer 3: Wiring Tests (test_03_wiring.py)

Test that components are connected. Assumes existence and configuration passed.

```python
# CORRECT - wiring only
def test_webhook_handler_has_runners_layer_attached(lambda_client):
    """Verify webhook handler has the runners layer attached."""
    response = lambda_client.get_function_configuration(
        FunctionName="TenULabsWebhookHandler"
    )
    layer_arns = [layer["Arn"] for layer in response.get("Layers", [])]
    assert any("TenULabsRunnersLayer" in arn for arn in layer_arns)

def test_sqs_handler_triggered_by_job_queue(lambda_client):
    """Verify SQS handler has job queue as event source."""
    response = lambda_client.list_event_source_mappings(
        FunctionName="TenULabsSqsHandler"
    )
    sources = [m["EventSourceArn"] for m in response["EventSourceMappings"]]
    assert any("TenULabsRunnersJobQueue" in arn for arn in sources)

def test_webhook_handler_can_write_to_job_queue(iam_client, lambda_role_arn):
    """Verify webhook handler role has sqs:SendMessage permission."""
    # Check IAM policy allows cross-service access
    ...
```

```python
# WRONG - invoking Lambda (that's e2e)
def test_webhook_handler_processes_events(lambda_client):
    response = lambda_client.invoke(
        FunctionName="TenULabsWebhookHandler",
        Payload=json.dumps({"test": "event"})
    )
    assert response["StatusCode"] == 200
```

## Fail Fast with Granular Diagnostics

Cryptic errors like "Lambda invocation failed" are unacceptable.

- Each test must be atomic: one assertion per test
- Tests must run in layer order (existence before configuration before wiring)
- When a test fails, the developer must know exactly what's wrong
- Failure messages must include resource names and expected values

## Boundary with E2E Tests

Post-deployment integration tests verify the deployment. E2E tests verify user journeys.

### This belongs in post-deployment integration:
- Lambda exists
- Lambda has correct timeout
- Lambda has Layer attached
- SQS queue exists
- SQS queue has correct retention
- Lambda has SQS trigger configured
- Layer contains expected files

### This belongs in e2e tests:
- Webhook receives HTTP request and returns 200
- Message flows through SQS to Lambda
- Label routing correctly identifies runner type
- Circuit breaker opens after failures
- Full runner provisioning workflow

**Rule of thumb**: If the test invokes a Lambda, sends an HTTP request, or sends a message to SQS, it's an e2e test.

## No Cleanup Required

Post-deployment tests MUST NOT create test artifacts. They only inspect what terraform created.

- Do: Read resource configuration (get_function, describe_table, get_queue_attributes)
- Do: Verify resource exists (get_function, describe_table, get_queue_url)
- Do: Check component connections (list_event_source_mappings, get Layers)
- Do NOT: Write test data to DynamoDB
- Do NOT: Send test messages to SQS
- Do NOT: Invoke Lambdas with test payloads

If a test needs cleanup, it's probably an e2e test.

## Fixture Usage

Use fixtures to:
1. Create AWS clients once per module
2. Cache resource identifiers (queue URLs, ARNs)
3. Download and cache layer contents for inspection

```python
# conftest.py
@pytest.fixture(scope="module")
def lambda_client(config):
    return boto3.client("lambda", region_name=config["aws_region"])

@pytest.fixture(scope="module")
def job_queue_url(sqs_client):
    response = sqs_client.get_queue_url(QueueName="TenULabsRunnersJobQueue")
    return response["QueueUrl"]

@pytest.fixture(scope="module")
def layer_contents(lambda_client):
    """Download layer and return file list for inspection."""
    # Get latest layer version
    response = lambda_client.list_layer_versions(LayerName="TenULabsRunnersLayer")
    layer_arn = response["LayerVersions"][0]["LayerVersionArn"]
    # Download and extract...
    return file_list
```

## Quick Reference

| If you want to test... | Layer | File |
|------------------------|-------|------|
| Lambda exists | 1. Existence | test_01_existence.py |
| SQS queue exists | 1. Existence | test_01_existence.py |
| DynamoDB table exists | 1. Existence | test_01_existence.py |
| Layer exists | 1. Existence | test_01_existence.py |
| Lambda timeout is 30s | 2. Configuration | test_02_configuration.py |
| Queue retention is 14 days | 2. Configuration | test_02_configuration.py |
| Table has TTL enabled | 2. Configuration | test_02_configuration.py |
| Layer contains file X | 2. Configuration | test_02_configuration.py |
| Lambda has Layer attached | 3. Wiring | test_03_wiring.py |
| Lambda has SQS trigger | 3. Wiring | test_03_wiring.py |
| IAM allows cross-service | 3. Wiring | test_03_wiring.py |
| HTTP request works | N/A | e2e tests |
| Message flow works | N/A | e2e tests |
| Full workflow works | N/A | e2e tests |
