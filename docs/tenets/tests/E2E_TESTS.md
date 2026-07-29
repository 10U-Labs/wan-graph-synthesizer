# E2E Test Tenets

These are the non-negotiable rules for end-to-end tests.

This repository has exactly one end-to-end tier, at
`test/scripts/seed/e2e/`. It covers the seed CLI, which is the only
entrypoint a person runs directly. Everything else is a Lambda behind API
Gateway, and the deployed side of those is covered by
[POST_DEPLOYMENT_INTEGRATION_TESTS.md](POST_DEPLOYMENT_INTEGRATION_TESTS.md).

## Table of Contents

- [Top of the Pyramid](#top-of-the-pyramid)
- [Hermetic by Construction](#hermetic-by-construction)
- [Run the Real Entrypoint](#run-the-real-entrypoint)
- [Assert on Observable Outcomes](#assert-on-observable-outcomes)
- [Last Line of Defense, Not First](#last-line-of-defense-not-first)
- [Cover the Failure Path](#cover-the-failure-path)
- [Fail Fast](#fail-fast)
- [Document the Journey](#document-the-journey)
- [Test File Organization](#test-file-organization)
- [Fixture Requirements](#fixture-requirements)
- [Position in the Workflow](#position-in-the-workflow)
- [Boundary with the Other Tiers](#boundary-with-the-other-tiers)
- [Quick Reference](#quick-reference)

## Top of the Pyramid

End-to-end tests are few. There are four today, and that is the right
order of magnitude.

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

Each one stands for a journey that, if broken, makes the tool unusable:
the CLI runs, the CLI writes what it is supposed to write, the CLI fails
when the far end fails. An edge case in a parser is not a journey, and it
is cheaper and clearer as a unit test.

```python
def test_seed_cli_exits_zero_against_the_stub(stub_api: StubApi) -> None:
    """The seed CLI exits 0 when the API accepts every write."""
    assert _run_seed(stub_api.url).returncode == 0
```

## Hermetic by Construction

An end-to-end test touches no live resource, sends nothing off the
machine, and costs nothing to run.

The far end is replaced at the boundary the entrypoint speaks to. For the
seed CLI that is HTTP, so `StubApi` from `lib/python/test_http_doubles`
serves a real localhost server and records every request. Everything on
this side of that boundary is the real thing: the real module, the real
argument parsing, the real inputs under `etc/`.

There is no staging environment and there is no end-to-end test against
production. If a journey can only be exercised against live AWS, it is
not an end-to-end test here. Either it becomes an inspection in the
post-deployment tier, or it does not exist.

That rule is what makes this tier free to run on every push, including
pushes that never touch AWS credentials.

## Run the Real Entrypoint

Invoke the entrypoint the way a person does, as its own process.

```python
def _run_seed(url: str) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m seed <url>`` as a subprocess against a stub API."""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([
            str(REPO_ROOT / "scripts"),
            str(REPO_ROOT / "lib" / "python"),
            str(REPO_ROOT),
        ]),
    }
    return subprocess.run(
        [sys.executable, "-m", "seed", url],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, check=False,
    )
```

Importing the module and calling a function inside it skips the argument
parsing, the module entrypoint and the exit code, which are three of the
things this tier exists to cover. Use `check=False` and assert on the
result, so a non-zero exit is a readable assertion rather than an
exception from the harness.

## Assert on Observable Outcomes

Assert what the outside world sees: the exit code, and the requests that
reached the far end.

```python
def test_seed_cli_writes_carrier_vertices(stub_api: StubApi) -> None:
    """The seed CLI writes carrier vertices to the API."""
    _run_seed(stub_api.url)
    paths = [path for _method, path, _body in stub_api.records]
    assert any("/carriers/" in path and path.endswith("/vertices")
               for path in paths)
```

Do not reach inside the process for internal state. If an internal value
needs asserting, that is a unit test over the module that owns it.

## Last Line of Defense, Not First

If an end-to-end test catches something a unit test could have caught,
the unit tests have a gap and the gap is the bug to fix.

| Issue | Should be caught by |
| --- | --- |
| A parsing error in one module | Unit |
| A mis-built request body | Unit |
| Two modules disagreeing | Integration |
| A wrong entrypoint name | End to end |
| An unhandled non-zero exit | End to end |
| A missing PYTHONPATH entry | End to end |

The tier's value is the wiring nothing else sees: module resolution,
argument handling, process exit codes, and the fact that the real inputs
in the repository are still readable by the real code.

## Cover the Failure Path

A tier that only covers success proves the entrypoint runs, not that it
reports.

```python
def test_seed_cli_fails_when_the_api_rejects_writes() -> None:
    """The seed CLI exits non-zero when the API returns an error status."""
    with StubApi(status=500) as api:
        result = _run_seed(api.url)
    assert result.returncode != 0
```

An entrypoint that exits 0 after every write failed is worse than one
that crashes, because a workflow gating on it goes green.

## Fail Fast

The stub is on localhost, so a correct run is immediate.

No retry loops, no polling, no sleeps. A test that waits is waiting for
something this tier does not have: there is no eventual consistency
behind a localhost socket. If a wait seems necessary, the double is
wrong, not the timeout.

## Document the Journey

Each test's docstring states the journey and the failure it stands for,
in one sentence. The tier is small enough that every test earns its
description.

```python
def test_seed_cli_writes_a_tenant_label(stub_api: StubApi) -> None:
    """The seed CLI writes a tenant label to the API."""
```

## Test File Organization

The seed script's tests carry all three tiers.

```text
test/scripts/seed/
├── conftest.py            # Shared seed fixtures
├── unit/
│   ├── test_seed.py
│   └── test_zayo_pops.py
├── integration/
│   └── test_contracts.py
└── e2e/
    ├── conftest.py        # The stub API fixture
    └── test_cli.py
```

The end-to-end directory holds one module per entrypoint, named for the
entrypoint. There is no split by journey type, because there is one
entrypoint and four tests.

## Fixture Requirements

An end-to-end fixture stands up the double, yields it, and tears it down
on the way out.

```python
@pytest.fixture
def stub_api() -> Iterator[StubApi]:
    """Run a localhost stub API recording PUTs for the duration of a test."""
    with StubApi() as api:
        yield api
```

Function scope, not module scope: each test gets a stub with an empty
record list, so one test's requests cannot satisfy another's assertion.

A test needing different far-end behaviour, such as an error status,
constructs its own `StubApi` in a `with` block rather than adding a
parameter to the shared fixture.

## Position in the Workflow

`seed.yml` runs the tiers in order, and only the last job talks to the
real API.

```text
static-analysis
  └── unit-tests
        └── integration-tests
              └── e2e-tests
                    └── seeding
```

```yaml
- name: Run end-to-end tests against a stub API
  run: >-
    PYTHONPATH=.:lib/python:scripts
    python3 -m pytest test/scripts/seed/e2e/
    --import-mode=importlib --confcutdir=test
    --verbose
```

`seeding` is the job that pushes the git-authored inputs to the live API.
It runs after the end-to-end tests pass, which is the whole reason the
tier is worth its cost: the CLI that is about to write to production has
just been run start to finish against a stub.

Note that a first `seeding` run can fail with `HTTP 403` on a resource
whose route was added in the same push, because `seed` and
`api_common_routing` are independent workflows racing on one push. Wait
for routing, then re-run the failed jobs.

## Boundary with the Other Tiers

| Post-deployment integration | End to end |
| --- | --- |
| The Lambda exists | The CLI runs |
| Its settings are right | Its exit code is right |
| Its role is attached | Its requests arrive |
| AWS reports it correct | The process behaves |

## Quick Reference

| To test | Tier |
| --- | --- |
| A function's return value | Unit |
| A request body's shape | Unit |
| Two modules agreeing | Integration |
| The CLI's exit code | End to end |
| The CLI's requests | End to end |
| A live resource's settings | Post-deployment |
