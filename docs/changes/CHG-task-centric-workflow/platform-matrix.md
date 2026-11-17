# 平台验证矩阵

| 平台/环境 | 影响与验证 | 命令或入口 | 结果 |
| --- | --- | --- | --- |
| Windows 本地开发 | PowerShell、路径、编码、Cookie 和静态站点启动；不保存平台特定路径 | `cd hexa-api; python -m pytest -q`；`cd client; npm test; npm run typecheck; npm run build` | not_evaluated |
| Linux CI / PostgreSQL | FastAPI、SQL 迁移、事务和异步执行；SQLite 测试不能替代 PostgreSQL 冒烟 | `python -m pytest -q hexa-api/tests`；执行 `migrations/002_tasks.sql` 建表并运行 API 冒烟 | not_evaluated |
| Chromium 桌面 1280×800 | 三段式布局、画布操作、运行时间线、检查器和状态可读性 | `cd client; npx playwright test -c playwright.config.ts` | not_evaluated |
| Chromium 移动 390×844 | 抽屉/底部面板、节点选择、继续、错误恢复和无溢出 | 同上，使用移动视口配置 | not_evaluated |
| 静态站点 | `/tasks/:id` 直接访问和刷新由部署回退到应用入口 | `npm run build`、`npm run preview`，Playwright 直接访问和刷新详情路由 | not_evaluated |
| client ↔ hexa-api | Cookie 认证、401/403、404、409、SSE 断线和幂等请求 | client API 测试、FastAPI TestClient、真实本地服务冒烟 | not_evaluated |

Gateway 仅作为 `hexa-api` 的外部执行依赖；Gateway 原有回归测试不属于本 Change 的直接实现范围，只有修改其调用契约时才补跑对应测试。
