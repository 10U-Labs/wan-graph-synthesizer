# SEQUENCE

Dependency order across `src/` — common infra, endpoints, and HTTP actions.
Each node is one workflow (`api_common_*`, `api_endpoint_*`). `A ─→ B` means B
is built on A: every endpoint reads the common `storage` + `routing` state, a
carrier/tenant write cascades to its builder (`carriers/merge`, `tenants/wan`),
and the `tenants/wan` POST action publishes the synthesizer image its create
task runs.

```text
api/common/storage ─┐
api/common/routing ─┤
                    ├─→ api/endpoints/carriers ─→ api/endpoints/carriers/merge
                    ├─→ api/endpoints/csps
                    └─→ api/endpoints/tenants ──→ api/endpoints/tenants/wan
                                                            ▲
                          POST tenants/wan (image) ────────┘
```
