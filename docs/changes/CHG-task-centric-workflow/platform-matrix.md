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

审批 HTTP 接线后续切片（2026-11-24）：Windows/Python 3.13 的真实本地 blob/SQLite、ASGI 和 Uvicorn TCP 入口验证鉴权读取、
决定重放、作用域隔离与取消，沿用内部请求头鉴权，无新增进程能力或操作系统分支。测试 TCP listener 限定 127.0.0.1 并动态选端口，
服务线程在 finally 退出；没有可执行 Shell 字符串或外网请求。真实 native Runner、完整审批 SSE/继续、Hexa UI、Linux 与部署
not_evaluated；当前 API 测试通过不代表 runtime coverage。结果见 Change `approval_http_slice`。

精确调用绑定切片（2026-11-24）：Windows/Python 3.13 的真实 SQLite/control store 验证 RFC 8785 canonicalization、
AES-GCM 密封 descriptor/原始参数/checkpoint、HR_SECRET_KEY 派生 key、进程重开、并发唯一派发、配置变更、错误 key、
密文篡改和异常/取消后的 unknown；HTTP 读回未泄漏密封字段。`rfc8785==0.1.4` 固定依赖，已有 cryptography 复用，
无新增 Shell、网络目标或平台分支。该切片是受信任 adapter 的内部 gate，不代表真实 Runtime 的副作用前拦截、native checkpoint、
Response 恢复、SSE 或 capability coverage。Linux、真实 Runner/Provider、部署和生产密钥轮换仍为 not_evaluated；结果见 Change
`approval_binding_slice`。

后续内部审批日志切片（2026-11-24）：复用 Gateway `control.db` 的原子 create/ETag CAS，无迁移、Shell 执行或新依赖。
Windows/Python 3.13/真实 SQLite 覆盖独立进程重开、多线程决定/开始/撤销竞争、原 store factory、过期/恢复/未知回执；测试子进程
通过 argv 调用 Python，不构造 Shell 命令。原用户提问测试存在默认 GBK 读 UTF-8 源码问题，回归以 `python -X utf8` 执行。
Linux、可选远端 control backing、真实 Runner、HTTP/SSE 审批及部署 not_evaluated；无 runtime capability 广告或 UI 修改。
证据与剩余接线统一见 Change `approval_journal_slice`。

## 2026-11-23 租约恢复与跨进程 fencing

| 平台/边界 | 实现影响、验证入口及结果 |
| --- | --- |
| Windows / Python / SQLite | 启动恢复跳过有效 owner、过期撤销 fence、迟到流与结果拒绝、同会话缓存刷新及 response ID 保留；相关结果见 Change `lease_recovery_fencing`。子进程以固定 Python 模块 argv 启动，数据库 URL 只经环境变量传入，不输出凭据。 |
| Windows 独立 Python 进程 / Linux PostgreSQL 容器 | 真实 PostgreSQL 隔离 schema：两进程竞争只有一个 owner、并发恢复仅一次 unknown、有效 owner 保持；47 项 PostgreSQL 回归及最终目标复验见 Change。数据库运行在 Linux，不代表执行器已在 Linux 验证。 |
| 本地 HTTP App / GatewayClient / PostgreSQL | 第二个 API lifespan 启动不破坏仍在流式执行的任务，原 owner 完成且只发生一次 HTTP 调用；受控 Gateway 不证明真实 Provider。 |
| Linux API / Runner / 真实 Provider / 部署 | not_evaluated；当前 Runner 镜像没有 SQLAlchemy，不能直接作为 API 验收环境。需在 hexa-api 交付镜像运行同一测试及部署冒烟；本轮不修改运行中容器或广告 UHP 审批能力。 |

API delivery image follow-up: `docker build -t hexa-orchestration-api-check:reaper hexa-api` completed from the final source; a disposable `python:3.12-slim` API container started and `GET /healthz` returned 200. The image smoke does not prove PostgreSQL wiring, real Gateway/BYOK, multi-replica failover, or Runner execution; those remain not_evaluated.

## 2026-11-23 ACP permission hook

Windows/Python 3.13 的 `runner/tests/test_acp_turn.py -k permission` 通过，覆盖原始 ACP 请求透传、显式返回和 handler
异常/空决定的 cancelled fail-closed。完整 `test_acp_turn.py` 未通过的三项是既有 `/bin/sh` 终端 fixture 在 Windows 上无法启动；
这三项属于 Linux Runner/终端路径，不能被 Windows 结果替代。`test_dcode_acp.py` 在 Windows 收集阶段还受 `pwd` 模块缺失影响，
未作为通过证据。Linux ACP 终端、真实 Agent、native checkpoint、Gateway durable approval 和 UHP capability 仍为
`not_evaluated`，本切片不宣称工具审批已完成。

## 2026-11-24 LangGraph native checkpoint adapter

Windows/Python 3.13 and the Linux Runner image used the optional, isolated
`runner/native_tests/requirements.txt`; both ran the real LangGraph HITL
middleware, SQLite checkpointer, Gateway sealed invocation gate and durable
journal. The controlled suite passed 31 tests on each platform, including
separate process capture/resume/replay, concurrent single start, deny/expiry/
void/native deny, changed checkpoint/configuration, and unknown-after-effect.
The boundary suite rejects memory checkpoints, batch/subgraph/free-form or
unsupported interrupts. This adapter is unregistered and its dependencies are
not part of ordinary Runner installation. Production Runner registration,
cross-process Runtime lease, dcode ACP, Response/SSE continuation, durable
denial continuation, real Provider, UHP capability publication and deployment
remain not_evaluated; `tool_approvals` is still not advertised.

## 2026-11-24 拒绝继续

Windows Gateway denial/journal/gate/HTTP/proposal schema 158 项通过；Linux Runner 镜像内 fresh venv
只安装固定 native test requirements 和 `jsonschema==4.25.1`，native/boundary/policy、denial/journal/gate/schema
140 项通过。独立 OS 进程以 argv 调用 Python，恢复共享 SQLite checkpoint/journal；deny 不创建工具文件，
投递 unknown 与工具 not_started 分开。原生模型为受控 ScriptedModel，不代表真实 Provider 或生产 dcode ACP；
Linux HTTP 未在本次组合执行。生产 Runner lease/注册、Response/SSE、Hexa UI、部署与远端 CI 仍未验证；UHP 能力广告未打开。

## 2026-11-24 Run capability binding

Windows/Python 3.13 的 Gateway Harness 摘要、Hexa API Gateway SSE、能力快照和 NodeRun 传播测试通过；摘要只覆盖安全能力身份，
不包含 MCP headers、env、auth 或插件文件。Gateway 在请求进入 session/provider/Runner 前校验 `metadata.capability_digest`，
旧 Gateway/fixture 因未返回摘要继续兼容但不具备一致性门禁。Linux、真实多副本 Gateway、Provider、Runner 和部署环境仍为
`not_evaluated`；本切片没有新增 UHP `tool_approvals` capability。

复用 ORM 与持久化 JSON 引用，无数据库列、Shell、原生模块或系统路径变更。Windows / SQLite 覆盖新 Run 恢复、引用身份和旧历史不变；HTTP 夹具覆盖实际 GatewayClient、失败响应、补跑和重启只读。当前源码真实 PostgreSQL、Linux 与真实 Provider 仍 not_evaluated；本批未新增迁移，也不宣称可发布。最终测试数量及 Chromium 流程证据见 Change `terminal_fanout_resume`；新增项级 UI 入口仍属后续工作。

## 2026-11-24 Runner 审批策略 fail-closed 接线

Windows/Python 3.13 的无平台依赖 Runner 策略单测 3 项通过，覆盖审批对象、显式 `null` 和字段缺失；`runner/server.py` 入口语法检查通过，并在状态检查/后端选择前拒绝显式审批策略。Windows 无法导入 Runner 完整服务（既有 POSIX `pwd` 依赖），因此真实 `/turn` HTTP 入口未在本机执行。Linux Runner、真实 ACP Agent、Gateway native checkpoint、Response/SSE continuation、PostgreSQL 和部署仍为 `not_evaluated`。该切片没有新增 UHP capability，`tool_approvals` 继续保持未广告。

## 工作区恢复边界（2026-11-24）

客户端使用标准 Promise、请求代次与 React 状态，无 OS API、Shell、路径或权限分支。Windows Chromium/Edge 在 1440x900 / 390x900 验证加载、失败重试、深链详情、明确 null 和辅助目录故障；真实本地 HTTP API/SQLite 的工作区隔离、模板版本和协调器旅程通过。Linux/macOS 浏览器未单独运行，不以 Windows 结果替代；本次未改后端、迁移或 Runner，复用已有后端证据。具体命令、数量与截图哈希见 Change `workspace_restoration_boundary`。

## 嵌套子编排调度（2026-11-24）

复用 Python、SQLAlchemy 和不可变 JSON 清单，无平台分支、路径或进程接口变更。Windows/SQLite 与 Windows API + Linux PostgreSQL 验证每层 readiness、并发槽位、记录预算及 UTF-8 输出上限；Linux API 镜像挂载最终源码运行相同专项，37 项通过。Chromium 普通/嵌套恢复旅程验证真实本地 HTTP API 与受控 Gateway；无 UI 修改。真实 Provider、原生审批和部署多副本故障切换仍未验证，实际命令与结果统一见 Change `nested_subgraph_scheduler_audit`。
