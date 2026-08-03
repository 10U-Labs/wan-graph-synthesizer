# A test runs in the workflow the change it guards arrives on

A test is worth nothing in a workflow the change it guards does not trigger. So the question "which workflow runs this test" is answered by asking what kind of push would break it, and putting the test where that push goes — not by which subsystem the test file happens to sit under.

The two halves of this repository's post-deployment testing divide cleanly along that line.

A test about how an API behaves, or about the shape of what was deployed, belongs in that endpoint's own workflow. `test_01_existence.py`, `test_02_configuration.py` and `test_03_wiring.py` under `test/api/endpoints/tenants/wan/post/post_deployment/integration/` ask whether the synthesizer Lambda exists, whether its runtime and memory match the declaration, and whether its role can reach the store. Each of those breaks when `src/api/endpoints/tenants/wan/post/**` changes, which is what `.github/workflows/api_endpoint_tenants_wan_post.yml` triggers on, and each runs there after `reconciliation` applies the stack.

A test about whether a WAN was actually rebuilt from the operator's configuration belongs in `.github/workflows/seed.yml`. `test_04_delivered_designs.py` measures each tenant's published network against the `backbone` block of its `etc/*.yml`. What breaks it is an edit to `etc/`, and a push touching `etc/` alone starts `seed.yml` and nothing else. `seed.yml` is also the workflow that delivers the edit: its `seeding` job runs `scripts/seed.py`, which PUTs the inputs and then POSTs one build per tenant. Deliver, rebuild and measure are three steps of one thing, and they run in one workflow in that order.

The file's own path does not move with the workflow. `docs/tenets/tests/OVERVIEW.md` says a test's location mirrors the code it covers, and `test_04_delivered_designs.py` covers the synthesizer, not `scripts/seed.py`, so it stays under `test/api/endpoints/tenants/wan/post/post_deployment/integration/` and `seed.yml` names that one file. The repository already does this elsewhere: `test/lib/python/test_published_designs/**` is run by `api_endpoint_tenants_wan_post.yml`, the workflow of the only code that imports it.

Two consequences follow, and both are accepted rather than overlooked. A workflow that runs a test file it does not own must list that file and its whole conftest chain in its `paths`, or a change to the test does not run the test. And a synthesizer change deploys in `api_endpoint_tenants_wan_post.yml` but is not measured against a rebuild until the next push that touches something `seed.yml` triggers on; moving `reconciliation` into `seed.yml` was offered as the alternative and declined.

See [an-either-is-a-question-for-the-user](an-either-is-a-question-for-the-user.md) for how the wrong half of this was chosen the first time.
