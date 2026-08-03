# The test tree splits on deployment phase, then on tier

Every subsystem under `test/` has the same four directories available to it, and the first split is whether a deployment has to exist:

```text
{subsystem}/
├── pre_deployment/
│   ├── unit/
│   └── integration/
└── post_deployment/
    ├── integration/
    └── e2e/
```

The phase is the top split because `docs/tenets/tests/OVERVIEW.md` says a tier may presume something exists, and two of the four presume a deployment: post-deployment integration asks what shape it came out, and end to end asks what a caller receives from it. Neither can be attempted on a bare checkout. The other two run anywhere.

A tier directory appears when a test exists to put in it and not before. `test/scripts/seed/` has no `post_deployment/integration/`, because there is no deployed `seed` whose shape could be read — it runs in the `seeding` job from a checkout. `test/api/endpoints/tenants/wan/post/` has no `e2e/`, because the three files under its `post_deployment/integration/` measure the deployment rather than making a caller's journey. An absent directory is the honest answer, not a gap to fill.

What a test drives decides its tier, not how much of the program it strings together. `test/scripts/seed/pre_deployment/integration/test_cli.py` runs `python -m seed` as its own subprocess over the repository's real `data/` and `etc/`, which sounds like the whole journey, and it is pre-deployment integration because the API it talks to is a localhost stub and nothing is deployed. It sat in a directory called `e2e/` until GitHub issue #49, and the name was load-bearing rather than merely wrong: `seed.yml` gated its `seeding` job on a job called `e2e-tests` that had only ever run against that stub, so a green end-to-end tier was reported by a test that touched nothing live.

Which directory a test sits in and which workflow runs it are separate questions. See [where-a-test-runs-follows-what-starts-it](where-a-test-runs-follows-what-starts-it.md) for the second one, and [read-test-tenets-first](read-test-tenets-first.md) for what each tier is required to assert.
