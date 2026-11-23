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


## 2026-11-23 集合项重试

本批无 UI、路径、进程或原生能力修改，使用 ORM 参数化查询和持久化 JSON 清单。Windows / SQLite / API 相关回归 157 项通过；本地真实 HTTP Gateway 夹具覆盖 fresh idempotency key 和重启只读；Chromium 现有编排、并行控制与终态 rerun 三项通过。Linux / 真实 PostgreSQL / 真实 Provider 继续 not_evaluated，无新增数据库迁移；本机结果不代表目标平台或真实模型成功。完整命令和限制见 Change `fanout_retry_slice`。


## 2026-11-24 二层 foreach

动态 DAG 后续切片：复用 JSON 清单和 ORM，无迁移、Shell、文件路径或原生能力变更。Windows/SQLite 覆盖局部拓扑、分叉汇合、条件、循环、重试/新 Run 恢复、暂停/取消/进程恢复；真实 HTTP 适配器与受控 Gateway 覆盖文本计划和重启只读。Chromium/Edge 验证配置保存重开及 1440/390 布局，浏览器经真实 hexa-api 验证 DAG 输入引用。真实 PostgreSQL、Linux、真实 Provider 和部署仍未验证，结果见 Change `dynamic_dag_slice`。

清单独立分页后续切片：无新增平台分支、进程或系统路径；Windows/SQLite 的 API/清单校验与 HTTP 重启读取、Chromium/Edge 分页错误/迟到响应、1440/390 历史截图和浏览器恢复证据见 Change `manifest_pagination_slice`。Linux、真实 PostgreSQL、真实 Provider 与部署限制保持未验证。

使用既有 ORM、JSON 清单与 React 表单，无新增操作系统路径、进程或数据库迁移。Windows/Python/SQLite 的最终编排回归和 HTTP 夹具证据见 Change `nested_foreach_slice`；Chromium/Edge 覆盖二层编辑保存重开、叶子历史和 1440/390 布局。浏览器端到端经真实 hexa-api 和受控 HTTP Gateway 验证失败后新 Run 恢复及历史刷新。Linux、真实 PostgreSQL、真实 Gateway/Provider 和生产部署仍为 not_evaluated，需在目标 Runner 上补验，本地切片不代表整体可发布。

## 2026-11-23 终态集合恢复

复用 ORM 与持久化 JSON 引用，无数据库列、Shell、原生模块或系统路径变更。Windows / SQLite 覆盖新 Run 恢复、引用身份和旧历史不变；HTTP 夹具覆盖实际 GatewayClient、失败响应、补跑和重启只读。当前源码真实 PostgreSQL、Linux 与真实 Provider 仍 not_evaluated；本批未新增迁移，也不宣称可发布。最终测试数量及 Chromium 流程证据见 Change `terminal_fanout_resume`；新增项级 UI 入口仍属后续工作。
