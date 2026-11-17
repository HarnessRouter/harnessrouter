## Hexa Cloud removal contract (2026-11-13)

Hexa does not ship HarnessRouter Cloud deployment, upload, destination workspace, hosted account, balance, or hosted provider handoff functionality. The local Gateway, ordinary user configured providers, UHP connections, Runner management, and browser runtime remain in scope. Source removal and runtime deployment are tracked separately; a source test pass does not prove an already running image has been rebuilt.

2026-11-13 本地部署已完成更新：`docker-compose.cluster.yml` 的 Gateway 从当前工作树重新构建并启动，镜像为 `sha256:9792a19fdc11bcdb0552ad90b01e268f0bffbb2483744af84889add40abdb587`。容器内 `gateway/app.py` 的 SHA-256 与源码一致。保留原数据卷，Runner 和 session-router 没有重建。

- Cloud targets/connect/status、admin connect、单 Harness upload 接口返回 404；批量上传的旧路径 `POST /v1/harnesses/upload` 因通用 Harness ID 路径匹配返回 405，专用上传处理器已不存在。
- 公共 OpenAPI 无 Cloud 路径；普通 integrations 返回 200，13 个服务商中无 HarnessRouter provider；原生 health、UHP、Runner 管理和 UHP connections 均返回 200。
- Gateway 聚焦回归 52 项通过；BYOK/providers/SetupSettings 组件回归 35 项通过；TypeScript、Python 编译、Next.js 生产构建和 `git diff --check` 通过。
- 部署后的 API key 创建/原生调用/BFF 调用/撤销，以及确定性 mock UHP 的连接/发现/JSON/SSE/续接/取消/Workflow 探针通过，临时 key/连接已清理。
- 受保护页面的浏览器视觉和响应式验收尚未完成；本次未重新运行全量 Console 测试，不据此声明全量 UI 验收通过。完整执行证据与剩余项见 [Cloud 删除变更记录](changes/CHG-hexa-remove-cloud-contract/change-record.yaml)。

# 开发验证记录

## 2026-11-13：真实 xred-bc Gateway 端到端验收

通过部署中的 Gateway 连接本机正在运行的 xred-bc UHP Runtime，完成了一次最小、只读的真实浏览器任务。验证使用临时组织和临时 UHP 连接，任务要求 Runtime 读取当前浏览器页面标题，不导航、不点击、不输入、不提交表单，也不修改数据；任务结束后连接已删除。

| 验收项 | 结果 |
| --- | --- |
| Gateway 保存真实 Runtime 连接 | 通过；使用容器可达地址 `http://host.docker.internal:8421`，密钥仅通过容器环境变量传递，接口返回脱敏配置 |
| 真实 Harness 发现 | 通过；发现 1 个真实 Harness，并由 Gateway 生成/映射本地 Harness 标识 |
| 真实单节点 Workflow 创建与启动 | 通过；Gateway 创建返回 200，`/run` 返回 202 |
| 真实 xred-bc 浏览器任务终态 | 通过；任务 `completed`，节点 `done`，Gateway 持久化 response ID |
| 真实任务输出 | 通过；Runtime 返回当前页面标题，并确认没有进行导航、点击、输入或数据修改 |
| 临时连接清理 | 通过；探针 `finally` 删除连接 |

本次探针最初用结构化消息数组作为 Workflow 的 `input`，被 Gateway 按接口契约以 422 拒绝；改为文档契约要求的字符串后重试成功。这一过程也确认了失败不会绕过 Gateway 的请求校验或留下未清理的连接。

此前对 xred-bc UHP Core conformance 的首次运行受到浏览器任务占用，返回 `409 session_busy`，不能作为协议结论。控制面空闲后重新运行仓库内 conformance suite，结果为 **41/41 passed、0 failed、0 skipped、0 errored**，结论为 `CONFORMANT — UHP 2026-10-19 (core)`。

## 2026-11-13：独立客户端远程 Workflow 状态一致性

继续按交付计划推进客户端与 Gateway 的集成边界。远程 Workflow 的任务快照由 Gateway 作为唯一权威来源；客户端只负责创建、启动、读取和轮询，不再把本地节点状态通过 PATCH 写回远端。这样可以避免并行节点执行期间，浏览器的旧快照覆盖 Gateway 已持久化的输出、重试次数或终态。

| 验收项 | 结果 |
| --- | --- |
| 客户端 Workflow 类型检查 | 通过 |
| 客户端构建 | 通过，输出 `client/dist` |
| 客户端测试 | **10 passed**；覆盖 Responses 流解析、远程记录归一化、本地草稿保留、旧轮询结果拒绝覆盖、API headers、稳定幂等键、请求体和路径编码 |
| 本轮客户端回归复核 | 通过；`npm test` 10 passed，`npm run typecheck` 通过，`npm run build` 通过 |
| 本轮 Console 管理页面回归复核 | **10 passed**；UHP Connections、Runner 管理和 edition 边界测试全部通过；Console `type-check` 通过 |
| 本轮 Gateway 联合回归复核 | **36 passed**；UHP Connections、Runner Admin、Workflow Tasks 和 Session Router 测试全部通过 |
| 远程任务启动失败处理 | 通过代码复核；失败后重新读取 Gateway 状态，不再将任务伪造为本地 `running` |
| 远程任务状态写回边界 | 通过代码复核；客户端已移除 Workflow PATCH 写回路径 |
| 远程任务创建重试 | 通过；幂等键使用客户端任务 ID，网络重试不会创建第二个 Gateway 任务 |
| 本轮 Gateway 镜像重建 | 通过；Console `/runners`、`/uhp` 路由均进入生产构建，Gateway 容器源码 SHA-256 与工作区一致 |
| 重建后部署健康检查 | 通过；Gateway、Runner 1、Runner 2、Session Router 均 healthy；`/healthz` 和 UHP discovery 均 200 |
| 重建后 API key/BFF HTTP 回归 | 通过；`mint=200`、`native_api_key=200`、`bff_api_key=200`、`revoke=200`、`after_revoke=401` |
| 重建后 UHP HTTP 回归 | 通过；连接保存、Harness 发现、JSON、SSE、续接、取消和 Workflow completed |
| Console 新增 UHP/Runner 页面测试 | **10 passed** |
| Gateway UHP/Runner/Workflow/Router 回归 | **36 passed** |

本轮（2026-11-13）再次执行了客户端、Console 定向测试、Gateway 联合回归、Compose 配置检查以及部署内 HTTP 验证。部署脚本输出分别为：

```text
API key: {"mint": 200, "native_api_key": 200, "bff_api_key": 200, "revoke": 200, "after_revoke": 401}
UHP: {"connection": "saved", "harness": "discovered", "responses": "json+sse+continuation+cancel", "workflow": "completed"}
```

部署验证脚本访问 Gateway 容器内部的 `127.0.0.1:8080`，因此必须在 `hexa2-gateway-1` 容器内执行，例如：

```powershell
Get-Content scripts/verify-deployed-uhp.py | docker exec -i hexa2-gateway-1 python -
```

从 Windows 宿主机直接运行会因为 `:8080` 未发布而连接失败；这不代表部署链路失败。脚本会优先读取显式的 `HARNESS_INTERNAL_KEY`，未设置时读取项目 `.env`，并且不会输出密钥。

本轮同时复核了 Console 全量 Jest：`149` 个测试套件中 `99` 个通过、`50` 个失败；失败测试共 `201` 项，主要是既有测试仍断言英文文案，而当前界面已使用中文文案，不能将其记为全量通过。新增管理页面和 edition 边界测试不在失败范围内。

## 2026-11-13：管理页面定向测试与 edition 边界修复

继续推进计划时补齐了此前没有覆盖的 Console 管理页面行为，并修复了两个边界问题：Runner 卡片视图现在和列表视图使用同一套 `alive`、`ready`、`accepting`、`draining` 状态判定；Runner 管理入口和路由只在 self-hosted 构建提供，避免 hosted Console 把用户带到被 BFF 拒绝的 `/internal/runners`；UHP 入口由当前组织是否属于 `NEXT_PUBLIC_HR_PLATFORM_ADMIN_ORGS` 控制，Gateway 仍是最终权限判断。

| 验收项 | 结果 |
| --- | --- |
| Console UHP 页面定向测试 | `UhpConnectionsPage.test.tsx`：4 passed；覆盖读取、密钥脱敏、保存、保留旧密钥更新、删除和读取失败 |
| Console Runner 页面定向测试 | `RunnersPage.test.tsx`：4 passed；覆盖非 ready 状态、注册、排空/恢复/注销保护和 Router 失败 |
| 两个新增管理页面联合测试 | **8 passed** |
| Console edition 导航边界测试 | `Shell.edition.test.ts`：2 passed；hosted 隐藏 Runner，非管理员 hosted 隐藏 UHP，self-hosted 暴露对应入口 |
| Console TypeScript 检查 | 通过 |
| Console 生产构建 | 通过；路由包含 `/uhp`，`/runners` 在 self-hosted 构建可用 |
| 后端 UHP/Runner/Workflow/Router 分组回归 | **36 passed** |
| UHP 分支协议定向测试 | **16 passed** |
| 页面兼容性修复 | Runner 请求不再依赖 `AbortSignal.timeout`，改用 `AbortController` 和可清理定时器 |

全量 Console Jest 仍有既有语言基线不一致：旧测试断言英文，而当前产品界面包含中文文案；这批失败没有计入本次管理页面验收，也未用它们声称全仓库通过。

## 2026-11-13：将管理页面修复部署到本机 cluster

本轮重新构建并仅重建了 Gateway 服务，沿用原有 `gateway-data`、Runner 和 Session Router 数据卷。新镜像包含当前工作区的 Console、Gateway 和 `/runners` self-hosted 路由边界修复。

| 验收项 | 结果 |
| --- | --- |
| `docker compose -f docker-compose.cluster.yml build gateway` | 通过；新镜像内容摘要为 `sha256:bec5978a6b994aba29e385b7485f8f6487b26ce7cb396a7305c952bc9e56aa6e` |
| `docker compose -f docker-compose.cluster.yml up -d --no-deps --force-recreate gateway` | 通过；未删除或重建数据卷 |
| Gateway、Runner 1、Runner 2、Session Router 健康状态 | 全部 healthy |
| 当前部署公开 `/api/harness/v1/uhp` | 200；`workflow_tasks: true` |
| 部署源码一致性 | 通过；容器内 `gateway/app.py` SHA-256 与工作区均为 `7c09894237773724460ebeae3e2d52e1c7b68505b03fe5a49322413508f41d8a` |
| `/uhp` 和 `/runners` HTTP 页面 | 均返回 200；页面主体由客户端渲染，未把原始 HTML 响应当作页面可视化验收 |
| 浏览器可视化复核 | 未完成；Windows Computer Use 无法可靠判定既有 Chrome 窗口的当前 URL，按安全策略停止，未进行登录、提交或数据修改 |
| 部署内 UHP HTTP 回归 | 通过：`verify-deployed-uhp.py` 返回连接保存、Harness 发现、JSON + SSE + 续接 + 取消、Workflow completed |
| 部署内 API key/BFF 回归 | 通过：`mint=200`、`native_api_key=200`、`bff_api_key=200`、`revoke=200`、`after_revoke=401` |

## 2026-11-13：UHP 连接修复与本机部署

本次已完成 UHP 集成范围的修复、回归测试、当前源码镜像构建和本机 cluster 部署。此前记录的其他待验收范围不因本次部署自动视为通过。

修复范围：首次保存连接引用未初始化变量；成功 SSE 分支不可达；取消请求使用了 GET；远端与 Gateway response ID 不一致；省略 harness_id 时续接无法找到外部 Runtime；跨组织/工作区访问；外部 Harness 未进入客户端发现列表；并发任务共用 response 映射文档造成覆盖。密钥仍保存在加密 SecretStore，接口只返回脱敏标记。页面展示供客户端调用的 Gateway Harness ID，并将 Runtime ID 放在提示中。Docker 忽略规则补充嵌套 node_modules、.next、dist，本次 Gateway 构建上下文由超过 1GB 降至 31.30MB。

| 验收项 | 结果 |
| --- | --- |
| `python -m pytest -q gateway/tests/test_uhp_connections.py gateway/tests/test_runner_admin.py gateway/tests/test_workflow_tasks.py session-router/test_router.py` | 36 passed，其中包含中断 `running` 节点恢复、Workflow service identity 和 dict/JSONResponse 返回形态回归 |
| 当前工作区 UHP/Workflow 联合回归复核 | `python -m pytest -q gateway/tests/test_uhp_connections.py gateway/tests/test_runner_admin.py gateway/tests/test_workflow_tasks.py session-router/test_router.py` | 36 passed；Python 编译、`git diff --check` 和 cluster Compose 配置检查通过 |
| UHP 回归范围 | 保存/更新/删除、密钥脱敏、稳定 Harness ID、后台字段转发、查询、POST 取消、续接、组织隔离、工作区发现过滤、SSE 首帧不等待终态、跨 UTF-8 chunk 中文、资源关闭、离线 503 |
| `./scripts/test-runner-readiness.ps1` | Linux 一次性容器中 6 passed |
| Console `npm run type-check --prefix ui` | 通过 |
| Console Docker Linux 生产构建 | 通过，包含 `/uhp` 和 `/runners` |
| 独立客户端 `npm test --prefix client` | 4 passed |
| 独立客户端 `npm run build --prefix client` | 通过，输出 `client/dist` |
| Python 编译、`git diff --check`、cluster Compose 配置检查 | 通过 |
| cluster 镜像构建 | Gateway、Runner、Session Router 均成功 |
| `docker compose -f docker-compose.cluster.yml up -d --force-recreate` | 完成，沿用原数据卷；Gateway、两个 Runner、Router 全部 healthy |
| 当前部署产物与工作区源码一致性 | 容器内 `/app/gateway/app.py` SHA-256 与工作区比较；镜像创建时间检查 | 通过：两者均为 `7c09894237773724460ebeae3e2d52e1c7b68505b03fe5a49322413508f41d8a`；Gateway 镜像于 2026-11-13 重新构建 |
| 当前部署栈 Workflow 运行时 | 在 Gateway 容器内部使用运行时内部密钥创建任务、调用 `/run` 并轮询终态 | 通过：创建 200、启动 202、终态 `completed`、节点 `done`；最新部署还通过了绑定外部 UHP Harness 的 Workflow HTTP 验证 |
| 当前部署栈 UHP HTTP 链路 | `scripts/verify-deployed-uhp.py` 在 Gateway 容器内启动一次性 mock Runtime，通过真实部署 HTTP API 验证 | 通过：连接保存与脱敏、Harness 发现、普通 JSON Responses、SSE、续接、取消、外部 Harness Workflow；临时连接已删除 |
| 当前部署栈 Runner 注册 | Gateway 容器内查询 Session Router `/runners` | 通过：2 个 Runner，均 `ready=true`、`accepting=true` |
| Gateway 内部 `/healthz` | 200，`ok=true`、`secrets_encrypted=true`；`vault=false` 表示未配置远程 vault，当前为本地 backing |
| 公开 `/api/harness/v1/uhp` | 200，discovery 包含 streaming、cancellation、harness_management、workflow_tasks |
| Console 鉴权 | 未登录页面重定向到登录；临时 API key 通过原生 Gateway 与 Console BFF 均为 200，撤销后原生 API 返回 401 |
| 独立客户端浏览器链路 | 本地 Vite 客户端 `http://127.0.0.1:4173`，使用临时 API key 访问相对 `/v1` 代理 | 通过：浏览器加载 Chat、Agent、任务页面并显示“已连接 Gateway”；Agent/任务请求无 `Failed to fetch`；临时 key 已撤销 |
| 独立客户端 API key 链路 | `scripts/verify-deployed-api-key.py`：创建临时 key、请求原生 Gateway 与 `/api/harness` BFF、撤销并复查 | 通过：`mint=200`、`native_api_key=200`、`bff_api_key=200`、`revoke=200`、`after_revoke=401`；key 未输出且已清理 |

当前部署镜像 ID：

- Gateway：`sha256:144b81b550f9be8b693c61b24faf6e490cf89b38d58c878fd3663f5fb35c6249`
- Runner（两个实例共用）：`sha256:020cf80d78bab35b27e36f71892845e292e3f45a9a8c49494e96318e5dc7f273`
- Router：`sha256:2aae9ebb441df879369c84cccbf5c08e5c996d69176bcc2bd07661d807597fb6`

容器内 `gateway/app.py` 与工作区 SHA-256 一致：`7c09894237773724460ebeae3e2d52e1c7b68505b03fe5a49322413508f41d8a`。生产路由清单包含 `/(app)/uhp/page`。由于 Docker Hub 当时返回 429，本次 Gateway/Runner 使用当前已验证基础镜像制作增量镜像，并覆盖当前工作区 Gateway、Runner 和 Console 构建产物；服务均已重新创建，原数据卷沿用未删除。

使用入口：登录 `http://127.0.0.1:3000/uhp`，填写外部 Runtime 地址和 Bearer 密钥后测试并保存。Docker Desktop 中连接 Windows 主机服务时通常使用 `http://host.docker.internal:8421`；Runtime 必须监听容器可达的地址。客户端 API base 为 `http://127.0.0.1:3000/api/harness`，使用 Gateway API key，通过 `/v1/harnesses` 获取本地 Harness ID，再调用 `/v1/responses`。客户端无需持有 Runtime 密钥。

验收边界：生产配置仍未长期保存外部 UHP 连接；真实 xred-bc 验收使用一次性连接并已删除。已完成本机独立客户端浏览器页面和 API key/BFF 链路验收，尚未进行跨浏览器验收，也未将全仓库测试记为通过。当前 `.env` 中 Anthropic 连接仍带占位标记，因此真实 Provider 工作流探针只能确认创建、调度和失败持久化链路，不能计为 Provider 成功验收。

## 2026-11-12

当前工作区尚未完成整体交付。下列结果仅证明各自明确列出的范围。

| 范围 | 验证方式 | 结果 |
| --- | --- | --- |
| 当前 Runner 源码 readiness | 一次性 Linux 容器，只读挂载 `runner/`，执行 `runner/tests/test_readiness.py` | 6 passed |
| 独立客户端 Responses 流解析 | `npm test --prefix client` | 4 passed |
| 独立客户端 TypeScript 与打包 | `npm run build --prefix client` | 通过 |
| 独立客户端流解析测试 | `npm test --prefix client` | 4 passed |
| 独立客户端 API key 请求头 | 代码检查 `gatewayHeaders` 覆盖 sessions、turns、harnesses、responses | 已接入 `Authorization: Bearer <API key>` |
| 独立客户端任务快照 | 客户端构建检查；`localStorage` 任务模型包含模板版本、节点、Agent 绑定和节点状态 | 已实现客户端本地快照与逐节点执行状态 |
| 独立客户端节点执行 | 客户端构建检查；`runTask` 调度就绪节点并保存节点输出/response id | 本地回退支持 DAG 就绪节点并行、依赖解锁、失败阻塞和每节点一次重试；远端任务由 Gateway run 接口调度 |
| Gateway 工作流任务 | `gateway/tests/test_workflow_tasks.py` | 已覆盖快照持久化、节点状态更新、组织隔离、环依赖校验和 Idempotency-Key 重放 |
| Workflow discovery 与 OpenAPI 契约 | `test_discovery_and_openapi_expose_workflow_capability` | `/v1/uhp` 声明 `workflow_tasks: true`；公开 OpenAPI 前缀包含 WorkflowTask CRUD 和 `/run` 路由 |
| 客户端远端任务恢复 | `listWorkflowTasks` / `createWorkflowTask` / `updateWorkflowTask` + 客户端构建 | 已接入 Gateway；启动后显示 `running`，每 2 秒轮询远端任务并同步节点状态、输出、response id 与终态；并行节点的 PATCH 更新按任务串行化，避免乱序覆盖 |
| Gateway 工作流执行 | `POST /v1/workflow-tasks/{id}/run` 与 `test_workflow_run_executes_ready_nodes_and_persists_results` | 已实现服务端后台 DAG 执行、就绪节点并行、节点重试、失败阻塞和状态持久化 |
| Gateway 工作流租约与恢复 | `test_workflow_recovery_restarts_durable_running_task`、`test_workflow_run_does_not_steal_live_lease` | 已实现启动扫描、durable lease admission/heartbeat/release、多副本抢占保护、写入前租约校验和重启后的任务接管；恢复不会保存用户 API key |
| 多进程 Workflow lease 竞争 | 两个独立 Python 进程共享临时 SQLite control store；副本 A 持有租约后由副本 B 竞争同一任务 | 通过：A 获得 `fence=1`；B 返回 `conflict=true`、`rejected=true`、`holder=replica-a`，未取得执行权；临时数据已清理 |
| 当前源码 Gateway 运行时 | 临时 Linux 容器只读挂载当前工作区 `gateway/`，验证 healthz、discovery、OpenAPI、任务 CRUD、`/run` 和终态轮询 | 通过：`workflow_tasks=true`；公开 OpenAPI 包含 3 个 WorkflowTask 路由；任务进入 `running` 后完成为 `completed`，节点为 `done`；临时容器和数据卷已清理 |
| 双 Gateway 共享持久化与恢复 | 两个临时 Gateway 进程挂载当前工作区源码，共享同一临时数据卷；副本 A 创建任务并持久化 `running`，重启副本 B 后从 durable 状态恢复 | 通过：B 可读取 A 创建的任务；重启后任务为 `completed`、节点为 `done`；临时容器和数据卷已清理 |
| Gateway Runner 管理与 Router | `python -m pytest gateway/tests/test_workflow_tasks.py gateway/tests/test_runner_admin.py session-router/test_router.py -q` | 已包含在最新 UHP 联合回归的 36 passed 中 |

运行中的本地 Compose 栈已重新创建并复核：Gateway、两个 Runner 和 Session Router 均为 healthy，`docker compose -f docker-compose.cluster.yml config --quiet` 通过。当前 Gateway/Runner 镜像覆盖了最新工作区源码，容器内 `gateway/app.py` 与工作区 SHA-256 一致；原有数据卷沿用。独立客户端的构建和 API key HTTP 链路已验证，但未将浏览器可视化交互本身记为通过。

重复执行 Linux readiness 测试：

```powershell
./scripts/test-runner-readiness.ps1
```

脚本使用本地 `harnessrouter/runner:latest` 提供 Linux 和运行依赖，实际测试代码与 Runner 模块来自当前工作区。测试依赖安装到一次性容器，工作目录和数据均写入临时路径。生产容器与生产数据卷不参与测试。

尚待验证或实现的范围：

- 独立客户端的 API key、Gateway 原生接口、Console BFF HTTP 链路和本机浏览器页面已通过；跨浏览器验收仍未计入。
- 对话切换期间的状态保存、失败恢复与真实 Provider 下的连续会话。
- 真实 Provider 下多节点 Gateway 工作流的完整端到端执行仍待验证；当前已完成双 Gateway 共享持久化、lease 竞争和启动恢复验证，代码级租约抢占保护和恢复测试也已通过。
- 真实 Provider 下的端到端任务验收，以及原计划文档的完整验收条目仍待完成；当前工作区没有可用于该验收的专用 Provider 凭据，不能把现有占位配置计为成功。
- 原计划文档的完整验收条目尚未定位，不能据此判定整体目标完成。

## 2026-11-13 20:52: Start/Letter console entry removal
`/start` 和 `/letter` 已改为重定向 `/studio`，Shell 菜单与相关组件、样式和图标已移除。`npm run type-check`、焦点测试 41 项、`next build` 通过；当前容器未重建，`/start` 和 `/letter` 仍先由登录门重定向，尚未验证登录后的 `/studio` 跳转。

## 2026-11-16：UHP 连接健康检查与调度保护

Gateway 为 UHP 连接增加独立健康观察：保存、列表刷新、手动检查和后台 30 秒周期会探测 `/v1/uhp` 与鉴权后的 `/v1/harnesses`；任务发送前强制检查，失效目标返回结构化 503，不自动切换 Agent。状态包括可达、鉴权、协议和 Harness 缺失，观察有效期 90 秒，响应和密钥保持脱敏。

- Gateway 健康、UHP 连接和 Workflow 定向回归：32 passed。
- Console UHP/Runner/edition 定向回归：11 passed；Shell/moved/safe-next 回归：41 passed。
- 独立客户端：33 passed；`npm run build`、Console `npm run type-check` 和 `npx next build` 通过。
- 2026-11-16 14:22（Asia/Shanghai）已重建并部署 Gateway。Docker Hub EOF 通过官方 AWS 公共镜像 `public.ecr.aws/docker/library/node:22-slim` 拉取后本地标记解决，未修改 Dockerfile/Compose；Linux Next standalone、类型检查和 Python compileall 均通过。
- 当前镜像为 `sha256:ccce37ae346de05a26ce0f5807f36fb85787eed2c9ce61a9b851f88003e7b71b`，保留标记 `harnessrouter/gateway:uhp-health-20261116`；容器启动于 `2026-11-16T06:22:05.535244521Z`。容器与工作区 `gateway/app.py` SHA-256 均为 `076abbc99a557003ad3cff85572145f08384eea215cf5e8f010ff8a80a290607`。
- 仅重新创建 Gateway，数据卷保留，两个 Runner 和 Session Router 未重建；四个 Compose 服务均 healthy，配置校验通过。
- `scripts/verify-deployed-uhp.py` 在旧部署因缺少 health 失败；新部署 exit 0：保存/脱敏/手动检查、JSON/SSE/续接/取消、Workflow 成功，以及离线 HTTP 503、鉴权失败、非法 JSON、Harness 删除的调度拦截及恢复均通过。失败目标没有收到任务 POST；Workflow `retry_limit=2` 实际尝试 3 次，Agent 不变。
- `scripts/verify-deployed-api-key.py` exit 0：创建、原生 API、BFF、吊销均 200，吊销后 401。验证临时连接已删除。
- Chromium 真实登录后验证 `/uhp` 失败保存保留、立即检查、删除；Start/Letter 菜单入口不存在，`/start`、`/letter` 均跳转 `/studio`。1440×900 和 390×844 无页面横向溢出，离线状态截图已检查；截图与哈希见 `docs/changes/CHG-uhp-health-gating/change-record.yaml`。
- 验收限制：现有 `xred-local` 地址 `host.docker.internal:8421` 不可达，健康保护已生效；没有将确定性 Mock UHP 的成功当作真实 xred Runtime 恢复证据。健康/鉴权/Harness 缺失状态标签有组件测试，但这些状态的浏览器截图及跨浏览器验收未执行。

## 2026-11-16：Hexa App 后端拆分与 Agent 管理热更新验证

本轮按前端展示、Python FastAPI 应用后端、现有 Gateway 执行面的拆分继续实现，未部署 Docker，也未修改 Gateway、Compose、Dockerfile 或 Cloud 契约。

| 验收项 | 结果 |
| --- | --- |
| FastAPI 后端回归 | 35 passed；HttpOnly Cookie、HMAC 会话、服务端 Gateway 代理、SSE 恢复、文件、工作空间和 Agent CRUD |
| client API 单测 | 39 passed；Agent 创建/删除、ID 编码、模型目录过滤、错误脱敏和幂等键 |
| direct client UI | 32 passed；对话、检查器、设置、工作空间、模板、移动布局 |
| app client UI | Chromium 3、Edge 3 passed；Agent 列表、创建失败保留、删除确认、模型重试、连续对话和刷新恢复 |
| FastAPI + 临时 HTTP Gateway 集成 | Chromium 2 passed；Cookie、SSE、连续对话、文件、下载、安全预览、Agent 增删 |
| Edge 集成 | 首个文件/对话流程 passed；Agent 管理流程两次在创建浏览器上下文时 Edge 进程退出，标记环境不稳定并待补验 |
| 构建与安全检查 | `npm run typecheck --prefix client`、`npm run build --prefix client`、Python compileall、`git diff --check` 通过；源码和构建产物未发现真实 Gateway Key |
| Cloud 删除契约 | `python -X utf8 -m pytest -q gateway/tests/test_hexa_no_cloud.py`：2 passed |

当前剩余：PostgreSQL 迁移及生产形态启动、真实普通 BYOK Provider、Memory/Template/Workflow 后端化、Edge 集成环境稳定性补验。认证方案是 HttpOnly 服务端会话 Cookie，不是 JWT；Gateway Key 仅由 `HEXA_GATEWAY_API_KEY` 注入 FastAPI 后端。

## 2026-11-16：工作台健康状态联动

- 工作台卡片、列表和 Agent 详情现在读取 Gateway `/v1/harnesses` 的 UHP `health`/`available`，连接状态覆盖任务历史统计；任务统计仍单独展示，不会用历史成功掩盖当前离线。
- 健康观察每 30 秒刷新，页面聚焦或从隐藏恢复时刷新；状态超过 Gateway 的 90 秒有效期显示“状态已过期”，刷新失败保留旧观察但不延长有效期。
- UHP 连接不可用时，工作台保留历史任务入口，禁用“新建任务”和消息发送，并显示原因及 UHP 连接入口；恢复后同一 Harness 自动恢复可发送。
- 新增组件和 Gateway 详情隔离测试；定向 UI 测试通过，Gateway 33 项 UHP/连接/Workflow 测试通过，Next 生产镜像已重建并部署为 `sha256:f6f2386f5fbfeb6112531e79239adc130116232849dbf5455d57da939c9d8c87`，容器 healthy。
- 已部署页面用真实现有 `xred-local`（当前不可达）验收离线工作台状态、详情禁用和移动端无溢出；真实 Runtime 恢复路径仍待 Runtime 恢复后补验。

## 2026-11-17：WisGit 开发快照提交前复核

本次将当前 Hexa 开发成果保存到 WisGit 开发分支，范围包含 Cloud 产品入口移除、UHP 健康保护与 Runner 管理、独立 client 和 hexa-api 任务系统，以及已有设计与验证资料。基线为 `c1d34c8` 的工作树；本次未新增产品行为，未将开发快照认定为发布验收完成。

| 范围 | 本次结果 |
| --- | --- |
| `cd hexa-api; python -X utf8 -m pytest -q tests` | exit 0；52 passed，包含认证、任务领域、HTTP 集成、工作区与 Gateway 协作 |
| `python -X utf8 -m pytest -q gateway/tests/test_hexa_no_cloud.py gateway/tests/test_harness_env.py gateway/tests/test_pinned_address.py gateway/tests/test_workspace_scope.py gateway/tests/test_uhp_connections.py gateway/tests/test_uhp_health.py gateway/tests/test_runner_admin.py gateway/tests/test_workflow_tasks.py session-router/test_router.py` | exit 0；104 passed；24 条 FastAPI 生命周期弃用警告 |
| `npm test --prefix client` | exit 0；18 passed |
| `npm run build --prefix client` | exit 0；TypeScript 与 Vite 构建通过；主 JS chunk 大于 500 kB 警告 |
| `npm run type-check --prefix ui` | exit 0 |
| Console 19 个相关 Jest 文件定向回归 | exit 1；13 suites / 193 tests passed，6 suites / 29 tests failed；失败文件见下文 |
| `python -m compileall -q gateway runner session-router hexa-api/app hexa-api/tests` | exit 0 |
| 暂存内容检查 | 排除真实 `.env`、依赖、构建产物、本地日志、`.wiscode` 和临时截图；保留版本化的设计验收截图 |

Console 失败文件：`NewSetup.test.tsx`、`setup/AgentHead.tabfocus.test.tsx`、`setup/Playground.branch.test.tsx`、`setup/TaskRail.test.tsx`、`start/open.test.ts`、`studio-live.test.tsx`。实际失败包含旧英文文案/按钮查询与中文界面不一致，以及 Windows 路径分隔符导致静态源码路由检查不匹配；本次没有修改或弱化断言。后续应按现有中文产品契约修复测试并复跑这六个文件；不能据当前结果宣称 Console 回归全部通过。

本次 E2E、真实 Provider、PostgreSQL 升级、Linux Runner readiness 与部署验证为 `not_evaluated`：本次目标是提交并推送现有开发快照，未重跑这些环境测试，已有 Change 中的限制继续有效。安全检查覆盖提交文件名、常见凭据格式和环境文件忽略规则；未将其视为完整安全审计或全历史凭据扫描。远端 CI、MR、合并与发布尚未执行。

## 2026-11-17：清理 Console 过时英文断言

按用户要求清除上次提交前复核发现的过时英文文案要求，保留六个文件的全部行为用例。NewSetup 不再要求显示 Auto，保存操作使用现有按钮结构定位；AgentHead 按 tab 顺序与选中状态验证键盘焦点和图标；Studio 使用健康样式、运行提示、错误提示与骨架状态验证行为；TaskRail 保留重试回调和恢复结果验证，重试按钮与测试夹具一致；Playground 使用当前中文响应 ID 按钮。创建路由检查中的文件相对路径统一使用 `/`，并移除静态白名单对旧英文错误文案的耦合。

更正上一节的归因：`start/open.test.ts` 的创建流程仍存在，失败主要来自 Windows 路径分隔符不匹配及静态白名单中的旧英文文案，不应作为已移除 Start/Letter 产品入口的证据。

- 验证基线：`c9fccb9` 加上述六个测试文件改动；未修改生产行为。
- 六文件首次定向回归：79 passed、1 failed；失败为测试夹具重试文案不一致，随后已修正。
- 原 19 文件相关 Jest 回归：221 passed、1 failed；唯一失败为本次新增的骨架结构断言把占位容器误认为应不存在，随后修正为验证骨架存在且文本为空。
- 最终只重跑受修正影响的 `studio-live.test.tsx`：exit 0，23 passed；其余 18 个文件的通过证据复用上次执行。最终相关范围共 19 个文件、222 个用例通过，未删除任何用例。
- `npm run type-check --prefix ui`：exit 0；`git diff --check`：通过。
- 当前 `conversation.test.tsx` 仍输出 React overlapping act() 警告，用例通过，未在本次扩大处理范围。
- 本次为测试维护，无生产行为改变；组件测试覆盖相关协作与失败恢复；浏览器 E2E、生产构建和部署未重跑，原有平台与发布限制继续有效。Windows 路径修复由本机测试验证，POSIX 路径沿用标准 `path.relative`/`path.sep` API，未另行声明 Linux 实测通过。
