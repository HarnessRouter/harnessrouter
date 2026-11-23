# 平台验证矩阵

| 平台/环境 | 影响与验证 | 命令或入口 | 结果 |
| --- | --- | --- | --- |
| Windows 本地开发 | PowerShell、路径、编码、Cookie、SQLite 和静态站点启动；不保存平台特定路径 | `python -m pytest -q hexa-api/tests`；`npm test --prefix client`；`npm run typecheck --prefix client`；`npm run build --prefix client`；`git diff --check` | 72 后端测试、26 客户端测试、类型检查、构建和 diff 检查通过；构建保留大 chunk advisory |
| Linux CI / PostgreSQL | FastAPI、SQL 迁移、事务和异步执行；SQLite 测试不能替代 PostgreSQL 冒烟 | `docker compose -f docker-compose.hexa-api.yml config`；启动 Compose 后运行 `python migrate.py` 和 API 冒烟 | not_evaluated；本机未配置 PostgreSQL/真实 Gateway 凭据 |
| Chromium/Edge 桌面 1280×800 | 三段式布局、画布操作、运行时间线、检查器、Artifact 下载和状态可读性 | `cd client; npx playwright test -c playwright.app.config.ts --workers=2`；`npx playwright test -c playwright.integration.config.ts tasks.spec.ts --workers=1` | UI 回归 72 项通过；真实 HTTP API＋SQLite＋Gateway fixture 任务套件 2 项通过；非空 Artifact 下载通过 |
| Chromium 移动 390×844 | 抽屉/底部面板、节点选择、继续、错误恢复和无溢出 | `cd client; npx playwright test -c playwright.app.config.ts --workers=2` | 受控 UI 套件覆盖并通过；非空 Artifact 移动端下载 not_evaluated |
| 静态站点 | `/tasks/:id` 直接访问和刷新由部署回退到应用入口 | `npm run build`、`npm run preview`，Playwright 直接访问和刷新详情路由 | not_evaluated |
| client ↔ hexa-api | Cookie 认证、401/403、404、409、SSE 断线和幂等请求、Artifact 下载 | client API 测试、FastAPI TestClient、Playwright 任务套件、真实本地服务冒烟 | 受控 API/SQLite/HTTP Gateway 夹具已通过；现有 4010 服务可访问；当前源码连接自托管 Gateway 因缺少 hr_selfhost Cookie 阻塞 |

Gateway 仅作为 `hexa-api` 的外部执行依赖；Gateway 原有回归测试不属于本 Change 的直接实现范围，只有修改其调用契约时才补跑对应测试。

## 2026-11-19 分页闭环验收

本批仅改变 Web 分页、请求隔离和 API 查询，没有新增操作系统路径、进程或原生能力。下表是本批最新结果；历史批次结果仍保留其各自范围，详细命令和限制以 Change 的 `workbench_pagination_closure` 为准。

| 平台/边界 | 当前结果 | 证据 |
| --- | --- | --- |
| Windows / Node / Python / SQLite | 客户端 36 单测、后端相关 30 测试、类型检查和构建通过 | Change 验证条目及 `client/.artifacts/pagination/build.log` |
| Chromium 与 Edge，1440×900 / 390×844 | 工作台目标回归 48 项通过；追加失败、原偏移重试、旧响应隔离、按钮及无横向溢出通过 | `client/.artifacts/pagination/app-report.json`、`visual-report.json` |
| 真实 HTTP API / SQLite / 受控 Gateway | 任务生命周期、恢复、Edge 路径通过；真实分页单项通过并验证移动端非空 Artifact 下载 | Change 三条 E2E 记录，明确初始失败与定向修复结果 |
| 本地静态构建预览 | `/tasks/71`、`/runs/19`、对应 JS 与重复访问均 200 | Change `static_preview`；生产反向代理未验证 |
| Linux / PostgreSQL / 真实 BYOK / 生产部署 | not_evaluated；继承已有环境限制，未称可发布 | 具备目标环境后补迁移、模型及部署冒烟 |


## 2026-11-23 循环与集合组合

| 平台/边界 | 影响、验证入口与结果 |
| --- | --- |
| Windows / Python / SQLite | 新增 iteration 默认值、旧库重复升级、保留输出和决定；API 与执行器回归的最终结果见 Change `loop_composed_fanout_slice`。无新增 Shell、原生模块或操作系统路径分支。 |
| 本地 HTTP Gateway 夹具 | 真实 HTTP adapter + SQLite 验证串联集合两轮、上一轮结果输入、分页与重启只读；不代表真实 Provider 执行。 |
| Chromium | 编排编辑保存运行重开 1 项、人工确认及并行/暂停/取消 2 项通过；本批没有 UI 源码或样式变更。 |
| Linux / PostgreSQL | not_evaluated；新增 009 及真实迁移测试已更新，按既有约定保留真库后续验证；SQLite 证据不替代 PostgreSQL。 |
| 真实 Gateway / BYOK / 生产部署 | not_evaluated；本批未改变 Gateway/UHP 调用契约，不宣称运行时审批已实现或整体可发布。 |
