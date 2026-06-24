# Unit Test Tenets

These are the non-negotiable rules for unit tests.

## Table of Contents

- [Unit Tests Are the Primary Line of Defense](#unit-tests-are-the-primary-line-of-defense)
- [Extreme Atomicity](#extreme-atomicity)
- [Test File Organization](#test-file-organization)
- [Complete Isolation](#complete-isolation)
- [Test Every Code Path](#test-every-code-path)
- [Descriptive Test Names](#descriptive-test-names)
- [Test Error Messages](#test-error-messages)
- [No Test Interdependence](#no-test-interdependence)
- [Fast Execution](#fast-execution)
- [Pre-Deployment Coverage Requirements](#pre-deployment-coverage-requirements)
- [Quick Reference](#quick-reference)

## Unit Tests Are the Primary Line of Defense

**Almost everything wrong should be caught by unit tests.**

The testing pyramid dictates that unit tests form the base - the number of unit tests should be absurdly larger than integration and e2e tests combined. If a bug could be caught by a unit test but wasn't, that's a failure of test coverage.

```
        /\
       /  \     E2E tests (few)
      /----\
     /      \   Integration tests (some)
    /--------\
   /          \
  /            \ Unit tests (many)
 /______________\
```

- Unit tests: Test a single component (function, class, module) in isolation
- Integration tests: Test how multiple components work together
- E2E tests: Test full user journeys

**Rule of thumb**: If you're testing a single component with all dependencies mocked, it's a unit test. If you're testing how two or more components interact, it's an integration test - regardless of whether network calls are involved.

## Extreme Atomicity

**One logical assertion per test. No exceptions.**

Each test must verify exactly one behavior. This ensures:
- When a test fails, you know exactly what broke
- Tests are independent and can run in any order
- Test names accurately describe what's being tested

```javascript
// CORRECT - atomic tests
describe('parseLabels', () => {
  test('extracts runner type from labels', () => {
    const result = parseLabels(['self-hosted', 'ecs', 'linux']);
    expect(result.runnerType).toBe('ecs');
  });

  test('extracts architecture from labels', () => {
    const result = parseLabels(['self-hosted', 'ecs', 'arm64']);
    expect(result.architecture).toBe('arm64');
  });

  test('defaults architecture to x64 when not specified', () => {
    const result = parseLabels(['self-hosted', 'ecs']);
    expect(result.architecture).toBe('x64');
  });

  test('throws LabelParseError when runner type missing', () => {
    expect(() => parseLabels(['self-hosted'])).toThrow(LabelParseError);
  });
});
```

```javascript
// WRONG - multiple assertions testing different behaviors
describe('parseLabels', () => {
  test('parses labels correctly', () => {
    const result = parseLabels(['self-hosted', 'ecs', 'arm64']);
    expect(result.runnerType).toBe('ecs');
    expect(result.architecture).toBe('arm64');
    expect(result.isSpot).toBe(false);
    // If architecture assertion fails, you don't know if isSpot is correct
  });
});
```

```javascript
// WRONG - testing error and success in same test
test('parseLabels handles valid and invalid input', () => {
  const valid = parseLabels(['self-hosted', 'ecs']);
  expect(valid.runnerType).toBe('ecs');

  expect(() => parseLabels([])).toThrow();
  // These are two different behaviors - split them
});
```

## Test File Organization

**One test file per source file. 1:1 mapping.**

```
src/api/endpoints/runners/lambdas/
├── webhook_router.js
├── job_starter.js
└── layer/
    ├── aws_clients.js
    ├── runner_labels.js
    └── webhook_ingress.js

test/api/endpoints/runners/pre_deployment/unit/
├── webhook_router.test.js       # Tests webhook_router.js
├── job_starter.test.js          # Tests job_starter.js
├── aws_clients.test.js          # Tests layer/aws_clients.js
├── runner_labels.test.js        # Tests layer/runner_labels.js
└── webhook_ingress.test.js      # Tests layer/webhook_ingress.js
```

Do NOT organize tests by behavior (test_happy_path.js, test_error_cases.js).
Do NOT put multiple source files' tests in one test file.

## Complete Isolation

**Unit tests must have zero external dependencies.**

- No network calls (HTTP, AWS SDK calls)
- No file system access (except test fixtures)
- No database connections
- No environment variable side effects

Mock everything external:

```javascript
// CORRECT - fully mocked
const { getSQSClient } = require('./aws_clients');
jest.mock('./aws_clients');

test('enqueues message to job queue', async () => {
  const mockSend = jest.fn().mockResolvedValue({ MessageId: '123' });
  getSQSClient.mockReturnValue({ send: mockSend });

  await enqueueJob({ jobId: 'job-1' });

  expect(mockSend).toHaveBeenCalledWith(
    expect.objectContaining({
      input: expect.objectContaining({
        QueueUrl: expect.stringContaining('JobQueue')
      })
    })
  );
});
```

```javascript
// WRONG - real AWS call
test('enqueues message to job queue', async () => {
  const client = new SQSClient({ region: 'us-east-1' });
  await client.send(new SendMessageCommand({...}));
  // This is an integration test, not a unit test
});
```

## Test Every Code Path

**100% branch coverage is the goal.**

Every `if`, `else`, `try`, `catch`, `switch` case, and early return must have a test.

```javascript
// Source code
function getRunnerType(labels) {
  if (labels.includes('ecs')) {
    return 'ecs';
  } else if (labels.includes('ec2')) {
    return 'ec2';
  } else {
    throw new LabelValidationError('Unknown runner type');
  }
}

// CORRECT - tests all branches
test('returns ecs when labels include ecs', () => {
  expect(getRunnerType(['self-hosted', 'ecs'])).toBe('ecs');
});

test('returns ec2 when labels include ec2', () => {
  expect(getRunnerType(['self-hosted', 'ec2'])).toBe('ec2');
});

test('throws when labels have no runner type', () => {
  expect(() => getRunnerType(['self-hosted'])).toThrow(LabelValidationError);
});
```

```javascript
// WRONG - only tests happy path
test('returns runner type', () => {
  expect(getRunnerType(['self-hosted', 'ecs'])).toBe('ecs');
  // Missing ec2 case and error case
});
```

## Descriptive Test Names

**Test names must describe the specific behavior being tested.**

Format: `[function/method] [condition] [expected result]`

```javascript
// CORRECT - descriptive names
test('parseLabels extracts runner type from labels array', () => {...});
test('parseLabels throws LabelParseError when labels array is empty', () => {...});
test('parseLabels defaults architecture to x64 when not specified', () => {...});
test('validateLabels returns false when runner type is missing', () => {...});
test('getInstanceType returns t3.medium for small size label', () => {...});
```

```javascript
// WRONG - vague names
test('parseLabels works', () => {...});
test('parseLabels test 1', () => {...});
test('error handling', () => {...});
test('should work correctly', () => {...});
```

## Test Error Messages

**When tests fail, the error message must explain the problem.**

Use assertion messages and custom matchers:

```javascript
// CORRECT - clear failure messages
test('webhook signature verification rejects tampered payload', () => {
  const result = verifySignature(tamperedPayload, signature);
  expect(result).toBe(false);
  // Jest shows: Expected: false, Received: true
});

test('job queue URL is constructed correctly', () => {
  const url = getJobQueueUrl('us-east-1', '123456789');
  expect(url).toMatch(/sqs\.us-east-1\.amazonaws\.com/);
  expect(url).toContain('JobQueue');
});
```

```javascript
// WRONG - unhelpful assertion
test('verifySignature works', () => {
  expect(verifySignature(payload, sig)).toBeTruthy();
  // If this fails, you just see "expected truthy, got falsy"
});
```

## No Test Interdependence

**Each test must be completely independent.**

- Tests must pass when run individually
- Tests must pass when run in any order
- Tests must not share mutable state

```javascript
// CORRECT - independent tests with setup
describe('CircuitBreaker', () => {
  let breaker;

  beforeEach(() => {
    breaker = new CircuitBreaker({ threshold: 3 });
  });

  test('starts in closed state', () => {
    expect(breaker.state).toBe('closed');
  });

  test('opens after threshold failures', () => {
    breaker.recordFailure();
    breaker.recordFailure();
    breaker.recordFailure();
    expect(breaker.state).toBe('open');
  });

  test('resets failure count on success', () => {
    breaker.recordFailure();
    breaker.recordSuccess();
    expect(breaker.failureCount).toBe(0);
  });
});
```

```javascript
// WRONG - tests depend on each other
describe('CircuitBreaker', () => {
  const breaker = new CircuitBreaker({ threshold: 3 });

  test('starts closed', () => {
    expect(breaker.state).toBe('closed');
  });

  test('records failure', () => {
    breaker.recordFailure(); // Mutates shared state!
    expect(breaker.failureCount).toBe(1);
  });

  test('opens after more failures', () => {
    // Depends on previous test running first!
    breaker.recordFailure();
    breaker.recordFailure();
    expect(breaker.state).toBe('open');
  });
});
```

## Fast Execution

**Unit tests must be fast. Milliseconds, not seconds.**

If a test takes more than 100ms, something is wrong:
- You're making real network calls (mock them)
- You're doing expensive setup (optimize or share via beforeAll)
- You're testing too much in one test (split it)

```javascript
// CORRECT - fast with mocks
test('fetches GitHub token from cache', async () => {
  mockSSM.getParameter.mockResolvedValue({ Parameter: { Value: 'token' }});
  const token = await getGitHubToken();
  expect(token).toBe('token');
  // Runs in <10ms
});
```

```javascript
// WRONG - slow real call
test('fetches GitHub token', async () => {
  const token = await getGitHubToken(); // Real SSM call
  expect(token).toBeDefined();
  // Takes 200-500ms per test
});
```

## Pre-Deployment Coverage Requirements

**Unit tests must catch these issues before deployment:**

| Issue Type | Must Be Caught By |
|------------|-------------------|
| Syntax errors | Unit tests (imports fail) |
| Type mismatches | Unit tests |
| Null/undefined handling | Unit tests |
| Edge cases (empty arrays, etc.) | Unit tests |
| Business logic errors | Unit tests |
| Error handling paths | Unit tests |
| Input validation | Unit tests |
| Single-file configuration parsing | Unit tests |
| Cross-file contract mismatches | Integration tests (local) |
| AWS resource misconfiguration | Integration tests (AWS) |
| Missing IAM permissions | Integration tests (AWS) |
| Network connectivity | E2E tests |
| Full workflow behavior | E2E tests |

If a bug could have been caught by a unit test, the test suite failed.

## Quick Reference

| If you want to test... | Test Type | Location |
|------------------------|-----------|----------|
| Function returns correct value | Unit | pre_deployment/unit/ |
| Error is thrown for bad input | Unit | pre_deployment/unit/ |
| Class method behavior | Unit | pre_deployment/unit/ |
| Mock interactions (call count, args) | Unit | pre_deployment/unit/ |
| JSON parsing/serialization | Unit | pre_deployment/unit/ |
| String formatting | Unit | pre_deployment/unit/ |
| AWS resource exists | Integration | pre_deployment/integration/ or post_deployment/integration/ |
| IAM permissions work | Integration | pre_deployment/integration/ |
| Lambda can be invoked | E2E | e2e/ |
| Full webhook flow works | E2E | e2e/ |
