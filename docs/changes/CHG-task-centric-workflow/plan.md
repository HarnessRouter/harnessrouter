# 实施方案

- 行为、边界与验收依据：`spec.md`。
- 任务、模板、运行快照和查看布局的保存语义统一以 [spec.md 的版本关系与保存边界](spec.md#版本关系与保存边界) 为准；实现步骤 1、3、5、6 均须覆盖该节验收，不将保存任务流程等同于保存模板。
- 视觉验收：`visual-contract.md`。
- 平台验收：`platform-matrix.md`。
- 执行记录：`change-record.yaml`。

## 方案与依赖

- 任务后端新增在 `hexa-api/app/tasks/`，复用现有认证、SQLAlchemy session factory、`AppWorkspace` 权限边界和 `GatewayClient`。
- `hexa-api` 负责状态机和调度；`client` 通过 app API 读写，不在 `main.tsx` 保存权威运行状态，不直接调用 Gateway 执行任务。
- 数据库使用新增迁移文件 `hexa-api/migrations/002_tasks.sql`；SQLite 测试工厂继续使用 SQLAlchemy metadata，生产 PostgreSQL 按部署流程执行迁移。
- 领域身份由服务端保存：Task.current_revision_id 指向 WorkflowRevision，Run.workflow_revision_id 固定执行版本，模板任务保留 TemplateVersion 来源引用；Run.execution_snapshot 保存执行快照，旧数据库迁移按版本号回填这些身份。
- 先实现领域状态与 API 契约测试，再实现持久化和执行器，最后接入 client 页面。每个行为按 Red → Green → Refactor 推进。
- 运行调度采用 `hexa-api` 进程内异步任务，首版按单实例部署；进程恢复时将无法确认的活动节点标记失败，不自动重放外部 Agent 请求。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 建立 `Task`、`WorkflowRevision`、`TemplateVersion`、`Run`、`NodeRun`、结果指针和人工决定的领域类型；实现状态转换、DAG/规模校验、输入引用校验、Task 状态推导和 `stale` 派生 | 先新增并运行领域单元测试 Red；覆盖 AC-2、AC-4、AC-6、AC-7、AC-9、AC-13 |
| 2 | 增加 SQLAlchemy 模型、`002_tasks.sql`、任务服务和认证/工作区权限检查；实现版本冲突、单活动 Run、幂等请求、写入前脱敏和分页查询 | hexa-api 持久化集成测试；覆盖 AC-1、AC-7、AC-12、AC-13 |
| 3 | 实现 `hexa-api` 任务、工作流、Run、NodeRun、模板 REST 接口和 SSE 事件流 | FastAPI TestClient/API 集成测试，覆盖错误码、权限、冲突、分页和响应字段；覆盖 AC-1、AC-2、AC-6、AC-10、AC-11 |
| 4 | 接入进程内执行器和 `GatewayClient`；实现并行调度、人工门控、继续、阶段续编、重试、跳过、取消、终态重跑、采用结果和恢复 | 使用 fake GatewayClient 的服务集成测试，再运行真实本地 Gateway 冒烟；覆盖 AC-3、AC-4、AC-5、AC-6、AC-8、AC-9、AC-13 |
| 5 | client 增加任务 API 客户端、任务列表、`/tasks/:id` 路由、共享 TaskCanvas、节点检查器、运行时间线和调试视图；client 只展示 API/SSE 状态 | client 单元/API 测试、Playwright 桌面和移动 E2E；覆盖 AC-1、AC-2、AC-10、AC-14 |
| 6 | 接入模板创建、保存为模板、空白任务创建、错误/加载/恢复状态和静态站点详情路由回退 | 模板集成测试、完整流程 E2E、`vite preview` 直接访问与刷新测试；覆盖 AC-1、AC-11、AC-14 |
| 7 | 执行安全、数据库迁移、删除任务、共享 Artifact 引用检查、PostgreSQL 建表冒烟和交付复核 | 运行 hexa-api 相关回归、client 相关回归、平台矩阵和安全数据流检查；更新 `change-record.yaml`，未验证项不得标记通过 |

## 恢复与收尾

- 新接口采用新增路径，旧 Gateway 接口不修改。任务功能异常时，client 保留任务列表和错误重试入口；服务端保留已写入的 Run 历史。
- 进程重启恢复采用“标记不确定失败、不自动重放”的安全策略；用户可以通过终态重跑显式开始新的 Agent 请求。
- 文档完成后，`spec.md` 作为任务领域长期契约；`plan.md` 和 `change-record.yaml` 保留实施证据，接口稳定后同步到 `hexa-api/README.md`。

## 2026-11-23 静态 DAG 并发边界切片

复用本 Change、现有 TaskExecutor、保存的 workflow JSON 和 Run 快照；不从其他工作区复制未提交生产实现。行为真源见 spec.md 的“静态 DAG 并发上限”，对应 AC-3、AC-6、AC-7、AC-8、AC-13、AC-15。先在领域和 API 边界写失败测试，再扩展 WorkflowSpec 的上限校验及 TaskExecutor 批次选择。显式人工节点不消耗 Agent 名额，批次选择发生在运行状态持久化和 Gateway 派发之前。

验证包括领域单测（类型与范围）、API/SQLite/受控 Gateway 集成（上限、真实并行、失败、取消、人工门控、历史快照）和真实 HTTP API→HTTP Gateway 夹具的无浏览器 E2E。最后运行现有任务领域、API、工作流、执行进度和恢复相关回归，记录实际证据至 change-record.yaml。无 UI、迁移或 UHP 调用字段变化，不新增客户端控件；此阶段不宣称全局限流、资源隔离、分支或循环已完成。回退代码不改写历史 workflow JSON；旧实现会忽略新增配置，因此回退前须停止依赖上限的运行，不得在旧执行器上启动它们。

## 2026-11-23 声明式条件分支切片

复用静态 DAG 的 `deps`、`NodeRun.skipped` 和 Run workflow 快照，增加受限 `condition` 对象，不引入表达式解释器或动态计划。先覆盖非法来源、路径、操作和值类型的领域 Red，再覆盖一条 Gateway 输出驱动的成功分支、跳过分支和显式允许缺失输入的汇合节点。条件判断发生在依赖完成、Gateway 派发之前；不匹配分支写入跳过状态并持久化原因。运行时只从成功 `inputRefs` 组装汇合上下文。

本切片不覆盖条件嵌套、短路表达式、循环、foreach、repeat、动态节点生成、运行中改图或 Gateway/UHP 协议字段。验证使用任务工作流单测和受控 Gateway 集成测试，再运行并发、任务 API、执行进度和 HTTP 回归；更新 AC-16 与 Change 证据后再进入下一片。

## 2026-11-23 有界重复切片

复用 `NodeRun.attempt`、当前 Run 快照和已有节点调试接口，把 `repeat` 限制为同一静态节点的最多 10 次追加尝试。`until` 只读取当前成功尝试的脱敏输出，满足后才释放下游；达到上限仍未满足则使用 `repeat_limit_exceeded` 结束 Run。先覆盖定义校验、终止条件和上限失败，再运行任务工作流、并发、API、执行进度及 HTTP 回归。

本切片不实现动态节点、DAG 回边、无界循环、foreach、跨节点循环、运行中更改 repeat 配置或 UHP 新字段。重复请求继续服从现有幂等和不确定副作用恢复规则。

## 2026-11-23 有界 foreach 切片

复用源节点输出、`NodeRun.attempt`、Run 快照和并发上限，把 `foreach` 限制为最多 10 个固定集合项的串行展开。每项输入保存 `foreach_item` 与 `foreach_index`，成功输出按索引聚合到同一节点的最新结果；空数组直接产生空聚合，非法或超限数组在 worker 派发前失败。先覆盖定义校验、逐项执行、保序聚合和上限拒绝，再运行任务工作流、并发、任务 API、执行进度及 HTTP 回归。

本切片最初不实现并行 foreach；当前后续实现已补充项级 `NodeRun`、工作流并发限制、聚合记录、失败停止、取消和恢复扫描。仍不实现嵌套 foreach、动态节点、无限展开、跨节点循环或运行中修改集合；这些能力需要单独定义循环迭代、失败重启和动态计划语义。

## 2026-11-23 编排配置界面切片

扩展共享工作流类型、workflowDraft 和保存载荷，确保任务、模板、协调器不丢失 max_concurrency。复用节点检查器并采用独立 fieldset，条件值使用本地文本草稿在保存时解析，repeat/foreach 以互斥模式编辑；校验失败聚焦错误并保留输入。运行属性展示快照配置和尝试信息。用 Node 单测验证配置复制与校验，用双浏览器受控 API 测试验证编辑、保存失败、重开、模板和运行快照，用真实 HTTP API/Gateway 夹具 E2E 验证保存再读取。保存桌面和移动截图并实际检查。协议审批仍是后续独立切片。

## 2026-11-23 Agent 能力与工具审批规范切片

先复用 UHP `2026-10-19` 已发布的 Plugin 子协议，读取 Harness 直接配置、启用插件派生能力、`skipped`、disabled tools
和 discovery capability，形成任务启动时的能力来源与 digest 快照。Hexa 只保存引用、版本、来源和安全摘要，不复制插件包或
secret；Gateway/Runner 继续负责插件物化、sandbox、MCP 连接和 command containment。

工具审批单独作为本地提案维护于 `protocol/proposals/tool-approvals/`。提案要求 Gateway 在副作用前持久化拦截精确调用、支持
幂等决定、精确恢复和执行回执，并要求 Runtime 原生拒绝优先于人工批准。它不把 `input_required` 或 function-call SSE 当作
授权机制，也不修改当前已发布协议、discovery、Gateway 或 Runner。实现顺序是 Gateway durable store 和 interception、Runner
原生约束、真实运行时 conformance，最后接入 Hexa Run 预检、审批卡和审计；在此之前工具审批能力必须保持未广告、未实现。

验证：草案 JSON Schema 的元校验和 6 个 shape tests；真实 A-01 至 A-09、跨重启恢复、原生沙箱和生产 Gateway 均为后续验证，不能
用 fake Gateway 或 schema tests 代替。

## 2026-11-23 完整引擎推进

用户将目标扩展为完整编排引擎，继续复用本 Change。按以下依赖顺序推进，实际结果只写入 change-record.yaml：

1. 统一展开状态机，移除串行集合覆盖项输出及业务 `items` 字段控制逻辑；同时修复 SQLite 旧库升级。
2. 收紧循环体闭包和汇合约束，分离轮次/尝试，添加上一轮结果；验证循环、展开、人工门控组合不会提前释放下游。
3. 为动态计划建立受限数据契约、预检与不可变清单，拒绝额外执行配置；本轮完成受限项展开，嵌套子执行和完整动态子图仍作为后续独立设计。
4. 补齐每个分支的取消、暂停、重试、进程恢复、资源上限和记录分页，客户端展示项级历史。
5. 在最后相关源码上完成领域、API、HTTP E2E、浏览器编辑/运行/历史恢复及桌面/移动验收；真实 PostgreSQL 与 Runtime 验证分别记录。

不得将前述受限动态项展开等同于已完成动态子图，或将仅通过目标测试的切片标记为完整引擎完成。

## 2026-11-18 工作台 API 接入批次

复用现有任务、模板、运行 REST/SSE 和工作台全高分栏样式，替换 `AppTasks` 中演示数据。列表按当前工作区分页读取；详情、模板编辑与运行快照分别加载。复用画布编辑器，增加任务/模板保存文案、异步保存和节点执行配置；任务草稿保存成功后才退出，失败保留草稿。运行只使用已保存版本，活动运行锁定语义编辑。SSE 生命周期交给 effect 管理，断线以只读轮询恢复。模板操作独立调用模板接口，不写本地演示模板。

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| A | API 客户端分页、工作区、结构化错误和保存版本参数；真实数据展示转换 | API 客户端与工作台数据单测；AC-1、AC-7、AC-13 |
| B | 任务创建、工作流编辑/保存、模板列表/版本/显式使用；补来源模板固定关系响应 | FastAPI 集成测试、浏览器受控接口测试；AC-1、AC-2、AC-11 |
| C | Run 历史、SSE/恢复、控制/人工继续、只读快照画布与脱敏调试 | 真实 HTTP App API + SQLite + HTTP Gateway 夹具 E2E；AC-3、AC-6、AC-7、AC-10 |
| D | 桌面/移动状态和现有导航回归、自查 | Chromium/Edge 目标 E2E、截图、类型检查与构建；AC-14 |

本批次不扩展 Artifact 存储、部署或生产 PostgreSQL 验收。执行证据及未覆盖场景写入同目录 Change；此前历史验证不能作为本批次的证据。

## 2026-11-18 剩余功能全量接入批次

本批次继续复用现有任务 REST/SSE、WorkflowRevision、Run 快照和 Gateway 文件代理。Artifact 采用 Gateway 文件引用，新增任务权限元数据和服务端下载代理；新增 005 迁移，PostgreSQL 由部署命令按 001 至 005 顺序执行，SQLite 仅由测试工厂自动建表。任务、Run、节点、调试尝试、模板和 Artifact 列表统一返回分页元数据，客户端按页读取并在详情/调试视图按需加载。Compose 验收配置只新增 hexa-api 与 PostgreSQL，不改变现有自托管 Gateway 入口。

实施顺序为：先写 Artifact、权限和分页 API 的失败测试；再实现模型、执行器产物落库、REST 下载和清理重试；随后接入客户端 Artifact/分页显示；最后验证迁移脚本、Compose、完整后端/客户端回归和真实 HTTP 集成。真实 PostgreSQL 与真实 BYOK 模型服务需要运行时凭据，缺失时记录 `not_evaluated`，不能由 SQLite 或 fake Gateway 代替。

## 2026-11-19 人工节点分层回归

围绕 spec.md 的人工门控契约补充 Unit、Integration、E2E 三层证据。项目未定义名为 L3 的正式标准，本批按三层覆盖解释用户要求，不能据此声明生产环境验证完成。

- Unit：显式 `human`、`human_gate`、旧 `requires_human` 和普通 Agent 分支。
- Integration：两种显式人工节点依赖完成后保持等待；非法选择不写入决定、不执行下游；合法选择仅推进同一个 Run，记录输入引用；重复幂等请求不追加决定。
- E2E：浏览器编辑并保存人工节点、启动、刷新后恢复等待、勾选结果、确认并继续，检查快照和决定；复用真实本地 HTTP App API、SQLite 与 HTTP Gateway 夹具。
- 复用已通过的任务生命周期 E2E 作为辅助函数回归；发生用例修改时仅重跑受影响旅程。执行命令、实际数量与限制统一写入 change-record.yaml。

## 2026-11-19 分页闭环改造

复用现有列表协议和保存边界，删除工作台自动耗尽分页的读取方式。任务、模板和跨任务 Run 列表每批最多 20 条；下一批由用户翻页触发。搜索与状态筛选在服务端先过滤再分页，Run 列表通过带任务权限的联表查询读取，不遍历所有任务历史。详情深链独立读取，不受列表首批范围限制。列表及详情追加页失败保留已加载内容，并允许重试；工作区切换或新查询后忽略旧响应。

模板响应另提供最新版本摘要，编辑与使用前重新读取该摘要，不遍历历史。历史版本、产物、调试尝试按服务端游标单批追加，按 ID 去重；游标按服务端 offset/limit 推进，不按去重后的数组长度推算。正常阅读、翻页和重放不写业务数据。

验证顺序：分页合并与游标单测 Red、服务端搜索/隔离/跨任务 Run/模板最新版本集成测试 Red、浏览器按需加载与失败重试 Red；再实现 API 与工作台。最终执行相关后端回归、客户端单测、Chromium/Edge 工作台回归、真实 HTTP App API＋SQLite E2E、桌面和移动截图检查、类型检查和构建。执行证据统一记录在 change-record.yaml；不扩展 PostgreSQL、真实模型凭据或生产部署范围。
