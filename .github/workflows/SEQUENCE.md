# SEQUENCE

Dependency order across `src/` — common infra, endpoints, and HTTP actions.
Each node is one workflow (`api_common_*`, `api_endpoint_*`). `A ─→ B` means B
builds on A: every endpoint reads the common `storage` + `routing` state, a
carrier/data-center/tenant write cascades to its builder (`carriers/merge`,
`data-centers/merge`, `tenants/wan`), and the `tenants/wan` POST workflow
(`*_post.yml`) lints, tests, and deploys the synthesizer's own stack
(`tenants/wan/post`, named after the workflow that owns it). The `tenants/wan`
dispatcher stack invokes the synthesizer by its deterministic derived name (from the
common module), so the two stacks stay decoupled -- each workflow owns and deploys
its own stack.

```text
api/common/storage ─┐
api/common/routing ─┤
                    ├─→ api/endpoints/carriers ─────→ api/endpoints/carriers/merge
                    ├─→ api/endpoints/data-centers ─→ api/endpoints/data-centers/merge
                    ├─→ api/endpoints/providers
                    └─→ api/endpoints/tenants ──────→ api/endpoints/tenants/wan
                                                      │
                                                      └─→ tenants/wan POST (tenants/wan/post)
```
