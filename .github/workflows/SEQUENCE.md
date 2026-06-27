# SEQUENCE

Dependency order across `src/` — common infra, endpoints, and HTTP actions.
Each node is one workflow (`api_common_*`, `api_endpoint_*`). `A ─→ B` means B
builds on A: every endpoint reads the common `storage` + `routing` state, a
carrier/data-center/tenant write cascades to its builder (`carriers/merge`,
`data-centers/merge`, `tenants/wan`), and the `tenants/wan` POST workflow
(`*_post.yml`) lints and tests the synthesizer worker Lambda the `tenants/wan`
stack deploys.

```text
api/common/storage ─┐
api/common/routing ─┤
                    ├─→ api/endpoints/carriers ─────→ api/endpoints/carriers/merge
                    ├─→ api/endpoints/data-centers ─→ api/endpoints/data-centers/merge
                    ├─→ api/endpoints/csps
                    └─→ api/endpoints/tenants ──────→ api/endpoints/tenants/wan
                                                      │
                                                      └─→ tenants/wan POST (worker)
```
