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

本切片最初仅覆盖串行 foreach；后续方案见并行展开、跨节点循环、受限动态计划、集合项重试与二层 foreach 各节。无限展开、完整动态子图或运行中修改集合不在当前支持范围；本段保留初始方案的历史边界，当前行为以 spec.md 为准。

## 2026-11-23 编排配置界面切片

扩展共享工作流类型、workflowDraft 和保存载荷，确保任务、模板、协调器不丢失 max_concurrency。复用节点检查器并采用独立 fieldset，条件值使用本地文本草稿在保存时解析，repeat/foreach 以互斥模式编辑；校验失败聚焦错误并保留输入。运行属性展示快照配置和尝试信息。用 Node 单测验证配置复制与校验，用双浏览器受控 API 测试验证编辑、保存失败、重开、模板和运行快照，用真实 HTTP API/Gateway 夹具 E2E 验证保存再读取。保存桌面和移动截图并实际检查。协议审批仍是后续独立切片。

## 2026-11-23 Agent 能力与工具审批规范切片

先复用 UHP `2026-10-19` 已发布的 Plugin 子协议，读取 Harness 直接配置、启用插件派生能力、`skipped`、disabled tools
和 discovery capability，形成任务启动时的能力来源与 digest 快照。Hexa 只保存引用、版本、来源和安全摘要，不复制插件包或
secret；Gateway/Runner 继续负责插件物化、sandbox、MCP 连接和 command containment。

工具审批单独作为本地提案维护于 `protocol/proposals/tool-approvals/`。提案要求 Gateway 在副作用前持久化拦截精确调用、支持
幂等决定、精确恢复和执行回执，并要求 Runtime 原生拒绝优先于人工批准。它不把 `input_required` 或 function-call SSE 当作
授权机制，不修改当前已发布协议和 discovery。实现顺序是 Gateway durable store 和 interception、Runner
原生约束、真实运行时 conformance，最后接入 Hexa Run 预检、审批卡和审计；在此之前工具审批覆盖必须保持未广告。

验证：草案 JSON Schema 的元校验和 6 个 shape tests；真实 A-01 至 A-09、跨重启恢复、原生沙箱和生产 Gateway 均为后续验证，不能
用 fake Gateway 或 schema tests 代替。

### 内部审批日志实施（2026-11-24）

按 AC-29 新增独立 `gateway/tool_approvals.py`，复用 control_store 的容器、异常和 ETag CAS，不新增数据库、HTTP 路由或依赖。
先写单元/SQLite 集成 Red，再实现 create/read/decide/reserve/start/finish/void/recover；所有授权关键失败传播，记录不设自动 TTL，
避免过期删除让同一 command 重获许可。原生拦截器将来负责 canonical descriptor、当前权限事实与安全 preview；日志只保存固定
字段和 digest。用独立存储实例、多线程及进程重开验证持久化和竞争，辅以原 control store/插件回归。完整 HTTP/runtime E2E
尚依赖下一阶段接线，必须单独记录未验证。回退模块及调用前停止接入中的审批任务，保留 control.db 历史；本切片无外部调用方。

## 2026-11-23 完整引擎推进

### 有界静态子编排实施（2026-11-24）

按 AC-32 新增 `subgraph` 静态子 DAG。先以 `test_subgraph.py` 建立保存校验、作用域、串行/并行、父子聚合和失败阻断的 Red，
再加入服务端预检、`subgraph_node`/`subgraph_aggregate` 清单状态机和分页清单归属校验。子图子节点固定继承已保存 Agent 配置，
不接受人工节点、集合/循环或模型生成拓扑；静态子编排最多支持两层，第三层及以上、动态子编排嵌套均拒绝。所有记录继续属于同一
Run，并计入 500 条 NodeRun 上限。实现还必须覆盖内层叶子/聚合的恢复映射、嵌套清单分页、客户端二层编辑入口和真实 PostgreSQL/Provider
验证；本切片不能宣称完整编排引擎完成。

### 精确调用 gate 实施（2026-11-24）

按 AC-31 新增 `gateway/approval_execution.py`，使用固定版本 rfc8785 库和已有 cryptography，复用 HR_SECRET_KEY 派生算法并以
HKDF 分离加密/承诺子密钥。Invocation 保存原 JSON 参数 bytes 与 opaque native checkpoint bytes，纯数据定义，不调用 Shell。
先写单元/SQLite Red，再给 journal create 增加内部密封字段以及受信任读取入口；无密封的旧记录保持可读可决定，但不得通过
bound gate 执行。密封内容与 Request 同 create，运行前校验当前 Invocation 与保存 Invocation 的 binding，并复用 CAS permit。
使用可观察 adapter 边界验证真实 SQLite 重开、并发/损坏/异常和取消，补 API 脱敏读回集成；完整 Runtime E2E 尚无 native adapter，
不把 controlled callback 当生产 coverage。回退保留加密历史和密钥；若后续已经派发，必须先停止 owner 并记录 unknown 再回退。

### 审批 HTTP 接线（2026-11-24）

按 AC-30 复用 `_principal`、严格 blob 读取、Session 权限和内部 CAS 日志。先写 API Red：真实本地 backing 中种入受信任
审批映射与日志，通过 ASGI 接口读取/决定/取消/删除；覆盖陌生主体、工作区限制、存储异常和 malformed body。扩展
CreateResponseBody 仅用于识别新策略字段并在最早入口拒绝；无 coverage 时不把审批输入带入旧文本规范化或远端转发。
新增 getter 以 mapping 寻址，不扫描组织所有日志；日志可额外核对 approval ID 与 command 的对应。取消和删除在已有副作用前
void journal，接口不触发工具。单元验证 guard/参数与 journal，集成验证 HTTP/blob/SQLite，真实 Provider/Runner E2E
仍未接线并记录限制。回退前确认无带审批的活动调用，保留 control.db 与 Response 历史；不升级已发布 schema 或 capability。

用户将目标扩展为完整编排引擎，继续复用本 Change。按以下依赖顺序推进，实际结果只写入 change-record.yaml：

1. 统一展开状态机，移除串行集合覆盖项输出及业务 `items` 字段控制逻辑；同时修复 SQLite 旧库升级。
2. 收紧循环体闭包和汇合约束，分离轮次/尝试，添加上一轮结果；验证循环、展开、人工门控组合不会提前释放下游。
3. 为动态计划建立受限数据契约、预检与不可变清单，拒绝额外执行配置；本轮完成受限项展开，嵌套子执行和完整动态子图仍作为后续独立设计。
4. 补齐每个分支的取消、暂停、重试、进程恢复、资源上限和记录分页，客户端展示项级历史。
5. 在最后相关源码上完成领域、API、HTTP E2E、浏览器编辑/运行/历史恢复及桌面/移动验收；真实 PostgreSQL 与 Runtime 验证分别记录。

### RunEvent 事实流实施（2026-11-24）

按 AC-34 在现有 Run/NodeRun 事务边界内新增 `RunEvent` 表和只读分页 API。先写成功生命周期和跨页行为 Red，再接入 Run 创建、节点派发/终态、
暂停/继续/取消、恢复 unknown 和失败路径；事件 payload 只保存脱敏身份与状态事实，不复制工具参数或凭据。SQLite 旧库通过启动升级创建表，
PostgreSQL 通过 010 迁移；验证领域/API/受控 Gateway、进程恢复、权限和幂等回归。后续 CommandReceipt、租约和 Gateway native approval 复用
该事件事实流，但不在本切片假设审批已经生产接入。

### CommandReceipt 回执实施（2026-11-24）

在每次 Gateway 派发前创建与 NodeRun 一对一的 `CommandReceipt`，使用服务端生成的 `command_id` 和覆盖 Agent/模型/执行上下文的
`request_hash` 固定调用身份；调用开始、完成、明确失败和不确定中断分别推进副作用状态。回执摘要接入 Run/NodeRun 读取和调试
详情，原始输入、工具参数、凭据和授权头继续留在脱敏边界之外。进程恢复会把活动节点的 `started` 回执收敛到
`unknown/reconciliation_required`，不得自动重新派发。先写成功、不确定和重启恢复测试，再运行任务编排回归与 PostgreSQL 迁移检查；
本切片不实现精确 reconciliation、Runtime lease 或 Gateway native tool approval。

### Run Lease 与 Heartbeat 实施（2026-11-24）

给 `Run` 增加 owner、fence、heartbeat 和过期时间；执行器在实际调度前原子取得租约，以固定 TTL 的异步 heartbeat 续期，并在
Gateway 回调写回前校验 fence。旧 owner 失去租约时只能放弃迟到结果，恢复路径把不确定副作用与回执收敛为 unknown；正常终态释放
租约。先覆盖竞争、过期接管、旧 owner 续租拒绝和释放，再运行任务/工作流/并发/动态子编排回归。租约不改变 UHP，不提供工具审批，也
不自动恢复副作用。

不得将前述受限动态项展开等同于已完成动态子图，或将仅通过目标测试的切片标记为完整引擎完成。

### 循环与集合组合的状态边界

为 NodeRun 兼容新增 `iteration`（旧记录默认 1），保留项索引与历史尝试。循环新轮次创建独立控制、item 和 aggregate；读取最新记录先比较轮次。集合完成聚合后先提交、重读，再调度下游，禁止读取已成功但无输出的控制记录。串联集合仍使用现有字段路径，不引入通配符或隐式递归扁平化。

循环轮次与单节点 repeat 尝试分别计数；新轮次的 attempt 从 1 开始。下一轮输入保存上一轮成功结果的引用，经过原有脱敏及输出边界；自动 repeat 和整轮追加均在事务内检查 500 条记录上限，并计入其他运行中集合预留的聚合名额。人工决定新增 iteration，旧决定默认第一轮；查询返回当前轮有效决定及独立历史，避免客户端将上一轮批准视为当前批准。验证覆盖领域规则、API/SQLite/受控 Gateway 组合、历史分页和真实 HTTP 入口；PostgreSQL 真库验证沿用已记录的后续验收边界。

## 2026-11-23 集合项重试

复用 fanout 状态机、NodeRun 输入和现有节点 retry 路径，控制记录新增不可变的项 ID 清单，不新增数据库列。先用受控 Gateway 在运行暂停时稳定保存集合失败，验证成功项不重复、替换项 append、幂等和非法引用拒绝；再为当前清单选择和记录配额编写单测。节点 retry 的可选请求体限定为 `item_node_run_id`，fingerprint 包含请求体，恢复任务交给现有执行器。聚合 attempt 与控制 attempt 一致，聚合 refs 保存实际上游 ID；消费者沿用现有分页调试协议。最后执行任务 API、并发、恢复和真实 HTTP E2E 回归。跨 Run 项级恢复与项历史 UI 继续实施，不以本接口完成声明代替完整引擎验收。

## 二层 foreach 实施

复用 fanout 状态机和输入 manifest，不增加数据库列或 UHP 消息。先前切片已加入二层基本展开与编辑器；本次补齐 AC-26 的生产边界：先写失败测试覆盖外层串行、部分成功的重试/新 Run 恢复、跨 Run 引用和空集合，再修正叶子派发、聚合预留和恢复映射。失败项恢复仍由外层项 ID 选择，成功叶子复用，历史记录不覆盖。暂停不再派发新叶子，取消及进程重启逐项保存不确定结果。

客户端继续复用检查器字段、现有分页与项历史列表，补充二层层级标签和只读叶子历史；单测覆盖校验和标签，浏览器覆盖保存重开、失败保留草稿与桌面/移动布局，HTTP 入口覆盖失败→恢复和只读重启。最后运行相关后端编排套件、客户端单测、类型检查、构建、Chromium/Edge 测试及文档检查。结果记 change-record.yaml；真实 PostgreSQL、Provider 与 Gateway 工具审批仍分别验收。回退前停止带二层清单的活动 Run，历史保留，旧执行器不得继续这些 Run。

## 清单分页实施（2026-11-24）

按 AC-27 复用 NodeRun 清单与任务鉴权，新增以控制/聚合 ID 为锚点的只读 items API，保留旧调试 API。先写领域/SQLite 与 HTTP 集成失败测试验证清单成员选择、深度和归属、分页过滤及零写入；再实现受限两层遍历与按 ID 分页。UI 提取独立项历史组件，独立初始/追加页及请求代次，恢复仍调用既有接口，调试历史另有加载更多按钮。先写客户端传输与双浏览器分页失败/迟到响应测试，再实现；补真实 HTTP 浏览器恢复及 390/1440 截图。验证后记录 Change 并提交；本批不增加迁移、UHP 字段或副作用执行。回退客户端后端同步版本即可，历史数据不变。

## 动态 DAG 实施（2026-11-24）

按 AC-28 扩展 dynamic_plan.topology，默认 list 保持严格契约。复用 dynamic_item、manifest 和聚合，不新增数据库列。独立 graph helper 校验局部拓扑与条件并选出就绪项，执行器生成固定 plan_refs；全图校验完成后才创建任何项。先写校验单测、API 分叉汇合/条件/非法图 Red，再实现后端；随后验证显式重试、终态复制与 plan_refs 重映射、循环和控制边界。客户端增加拓扑选择与快照标识，复用项历史，不把原画布改成可编辑的运行态图。测试覆盖单元、API/SQLite、HTTP 适配器/浏览器端到端和双浏览器配置重开，执行结果统一记录 Change。无 UHP 变更；回退前停止 DAG 活动运行，旧执行器不得继续带 DAG 配置的 Run。

## 受限动态子编排实施（2026-11-24）

在现有静态 `subgraph` 状态机上增加可选 `dynamic` 来源描述，不新建独立 Run 类型、不改变 NodeRun 表和 UHP。先以领域/API 测试覆盖来源路径、严格节点字段、局部依赖/输入引用、环、节点/边上限和“首次 Gateway 调用前不部分展开”；再复用 `subgraph_node` 清单、局部 DAG 就绪选择、聚合、暂停/取消和恢复映射。动态节点只继承父节点已预检的 Agent、模型、权限和能力快照；动态输出不得携带执行配置。

客户端增加动态子编排配置字段和快照/历史标签，使用与静态子编排相同的清单分页。静态子编排编辑器提供有限的二层入口，不提供第三层
入口；验证后端单元、API/受控 Gateway、暂停/失败/终态恢复、客户端校验、保存重开和窄屏编辑；真实 Provider、PostgreSQL、部署和
native tool approval 仍按既有独立门禁记录。动态子编排不得与静态节点清单同时配置，也不得递归嵌套。

## 终态集合恢复实施

### 项级历史界面接入

复用 RunSnapshot 的 debug 请求、分页代次和 action 回调。先为当前清单操作资格与请求载荷写单测，再写浏览器失败测试；新增独立历史列表组件，使用原生 ol/li/details/button 和现有 tokens。列表只读取已加载页，加载更多沿用原偏移；提交失败保留内容。扩展 app-api 类型与可选重试项字段，终态调用现有创建 Run 恢复 API。验证单元/API、受控浏览器错误与分页、真实 HTTP 夹具运行失败恢复、1440/390 截图和类型构建。

先扩展 RunBody 为严格的恢复字段组合并覆盖 API Red；复用当前 manifest 和 retry_fanout，建立恢复预检与复制助手，将 source Run 的成功结果和当前项映射为新 Run 记录，再追加选定重试。保存来源追踪，循环历史成功引用按需复制并映射，旧人工批准不继承。事务检查配额和身份，失败全部回滚。验证四种集合模式、非法引用、输入与版本变化、循环、人工确认、幂等以及 HTTP Gateway 夹具的失败→新 Run→重启历史旅程；后续 UI 复用这些 API。

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
