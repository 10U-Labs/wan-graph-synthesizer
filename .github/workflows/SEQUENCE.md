# SEQUENCE

Dependency order across `src/` — common infra, endpoints, and HTTP actions.
Each node is one workflow (`api_common_*`, `api_endpoint_*`). `A ─→ B` means B
builds on A: every endpoint reads the common `storage` + `routing` state, a
carrier/tenant write cascades to its builder (`carriers/merge`, `tenants/wan`),
and the `tenants/wan` POST workflow (`*_post.yml`) pushes the synthesizer image
into the ECR repo the `tenants/wan` stack creates, which its Fargate task runs.

```text
api/common/storage ─┐
api/common/routing ─┤
                    ├─→ api/endpoints/carriers ─→ api/endpoints/carriers/merge
                    ├─→ api/endpoints/providers
                    └─→ api/endpoints/tenants ──→ api/endpoints/tenants/wan
                                                  │
                                                  └─→ tenants/wan POST (image)
```
