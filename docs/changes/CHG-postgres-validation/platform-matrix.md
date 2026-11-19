# 平台矩阵

| 环境 | 实现影响 | 测试入口 | 结果 | 证据与限制 |
| --- | --- | --- | --- | --- |
| Windows host / Python 3.13 / SQLite | 默认测试工厂和本地开发数据库 | `python -m pytest` affected hexa-api tests | pending final rerun | SQLite does not enforce PostgreSQL foreign keys by default |
| Windows host / Docker Desktop Linux / PostgreSQL 16 | SQL migrations, foreign keys, transaction and Compose startup | `.artifacts/postgres/validate.py`; PG opt-in pytest lane | passed | isolated project and volume only; no production data |
| Linux container / FastAPI + PostgreSQL | Image dependency install, migration-before-start, healthcheck, HTTP cookie/API | `docker compose ... up --wait`; `.artifacts/postgres/http_check.py` | passed | controlled Gateway endpoint was not needed for task persistence check |
| macOS / native PostgreSQL | Platform-specific packaging and runtime | target host required | not_evaluated | run migration and API smoke in CI or target host |
