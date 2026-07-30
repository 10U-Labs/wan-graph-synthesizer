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

There are two workflows to wait for, not one, and the status code says which one is behind. A new resource needs the route (`api_common_routing`) *and* the tenants handler that stores it (`api_endpoint_tenants`, whose `_INPUTS` lists the collections it will accept). A missing route answers `HTTP 403 Forbidden`, since API Gateway rejects a path it does not define; a route whose handler has not caught up answers `HTTP 404 Not Found`, since the request reaches the old Lambda and it does not know the collection. Confirmed on 2026-07-30 while adding the `degree-exempt-backbone-nodes` resource: the seed run 404'd on the new PUT with `api_common_routing` already green and `api_endpoint_tenants` still running, and the rerun passed once both had finished.
