# SEQUENCE

Deploy order across `src/`. Each node is one stack (its `src/` path), plus the
two image/data steps (`build`, `seed`). `A + B └─→ C` means C reads A and B.

```text
api/common/storage
api/common/routing

api/common/storage + api/common/routing
    ├─→ api/endpoints/carriers
    ├─→ api/endpoints/csps
    ├─→ api/endpoints/tenants
    ├─→ api/endpoints/carriers/merge
    └─→ api/endpoints/tenants/wan

api/endpoints/tenants/wan
    └─→ build

api/common/routing + api/endpoints/tenants
    └─→ www/spa

api/endpoints/* + build
    └─→ seed
```
