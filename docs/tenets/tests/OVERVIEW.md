# Test Tenets

How tests are organized in this repo and the rules CI enforces. Adapted from
the 10ulabs.com test tenets to this repo's actual layout (a single gate
workflow over `test/unit`, `test/integration`, and `test/e2e`, rather than
per-endpoint pre/post-deployment trees).

## Tiers

- Unit (`test/unit/`): pure, hermetic, no network or AWS. Every branch is
  exercised; the optimizer, the pipeline stages, the graph serializers, and the
  Lambda handlers are all unit-tested with mocks. Gated at 100% coverage.
- Integration (`test/integration/`): wider in-process flows that wire several
  modules together, still without real AWS, using mocked or synthetic data
  (never real production `etc/` configs).
- End-to-end (`test/e2e/`): the full design pipeline over synthetic fixtures,
  asserting the composed result.

Infrastructure (the OpenTofu stacks) is checked by a separate `terraform` job
that runs `tofu init -backend=false` + `tofu validate` on every stack, with no
AWS credentials.

## Reusable test utilities (`lib/python/`)

Shared helpers live in `lib/python/` so no fixture is duplicated across tests
(which the copy-paste check would flag):

- `repo_utils`: locate the repository root.
- `module_utils`: load a Lambda handler file by path, exactly as the runtime
  loads it, so tests exercise what ships.
- `s3_store_mock`: a botocore-free stand-in for the S3, ECS, and Lambda clients
  (`fake_s3`, `fake_ecs`, `fake_lambda`), shared by every endpoint's tests.

Put a helper at the highest level where it applies; do not duplicate it.

## The per-endpoint handlers

Each REST endpoint is a self-contained single-file Lambda (`stdlib` + `boto3`),
so the handlers intentionally repeat small boilerplate. Their tests are
consolidated into one parametrized `test/unit/test_endpoint_handlers.py` so
there is no cross-file duplication, and the copy-paste scan compares each
handler only against `lib/python/`, never against its siblings.

## Rules the gate enforces

- `pylint --fail-on=C,R,W --fail-under=10.0` on source and on tests
  (run separately), 100-character lines.
- `mypy --strict --explicit-package-bases` on source and on tests.
- `jscpd --threshold 0`: no duplicated code.
- `pytest test/unit/` with `--cov-branch --cov-fail-under=100`.
- One `assert` per test (`assert-one-assert-per-pytest`).
- No inline linter directives and no linter config files
  (`assert-no-inline-directives`, `assert-no-linter-config-files`).

## Pre-flight before pushing

The gate fails one error at a time, so run the same checks locally first in a
virtualenv (pylint, mypy, jscpd, and the unit suite with coverage). This is a
local smoke check; CI remains the source of truth.
