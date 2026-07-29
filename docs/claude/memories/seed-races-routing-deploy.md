# Seed races the routing deploy

Adding a new per-tenant store resource — a new `/tenants/{tenant}/<resource>`
path in `openapi.json` plus a `seed.py` PUT — can fail the **seed**
workflow's `seeding` job on the first push to `main` with `HTTP 403
Forbidden` on the new resource's PUT, while every existing resource PUTs
fine.

The 403 is API Gateway rejecting an undefined route. `seed` and
`api_common_routing`, which deploys the OpenAPI routes, are independent
path-filtered workflows triggered by the same push, so `seed` can reach
the live API before the new route exists. It is a cross-workflow
deploy-ordering race, not a code defect. Confirmed on 2026-07-02 while
adding the `convergence-promotion` resource: `api_common_routing` went
green and `seed` 403'd on the new PUT.

Wait for `api_common_routing` to succeed, then re-run the failed seed job
with `gh run rerun <run-id> --failed`; it passes on the second attempt. Do
this explicitly rather than waiting for the next commit to cover it — a
later commit that does not touch `etc/`, `openapi.json` or `seed.py` will
not re-trigger `seed` at all, and the run stays red.
