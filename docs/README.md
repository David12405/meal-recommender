# Docs

Tài liệu học — đọc theo thứ tự số để hiểu codebase từ trên xuống.

| File | Nội dung |
|---|---|
| [00-overview.md](00-overview.md) | Kiến trúc tổng, flow 1 request, đọc từ đâu |
| [01-models.md](01-models.md) | Pydantic: enums, domain, input, output |
| [02-core.md](02-core.md) | config, cache singleton, logging, exceptions |
| [03-services-data.md](03-services-data.md) | db_loader, unit_converter, missing_ingredient, shopping_list |
| [04-services-solver.md](04-services-solver.md) | constraints C1–C4, objective, CP-SAT, relaxation, orchestrator |
| [05-utils.md](05-utils.md) | Công thức dinh dưỡng + date helpers |
| [06-api.md](06-api.md) | FastAPI routes, DI, exception mapping |

Ngoài ra:
- [../CLAUDE.md](../CLAUDE.md) — contract gốc giữa AI và team (schema, nguyên tắc, §15 Q&A)
- [../README.md](../README.md) — quick start cho người chạy service
