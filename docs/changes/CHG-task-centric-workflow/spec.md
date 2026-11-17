# 任务模块设计规范 v1

- 需求来源：用户确认的任务模块产品方向（2026-11-16）。
- 实施方案：`plan.md`。
- 关联视觉与平台约束：`visual-contract.md`、`platform-matrix.md`。
- 实现边界：`client` 是展示和操作端；`hexa-api` 是任务领域后端；Gateway 只负责被 `hexa-api` 调用的 Agent 执行能力。

## 目标行为

Hexa 用一个任务对象承载完整工作过程。用户从“我的任务”创建或打开任务，在任务详情中编辑工作流、启动运行、处理人工选择、查看结果和调试节点。

以下是本规范要求支持的完整成功运行示例。它描述后端的工作流、状态和数据变化，不规定用户在界面上的点击顺序。

### 完整运行示例：并行调查、人工选取、双重校验和报告

任务 `安全事件调查` 的 `WorkflowRevision 7` 包含以下节点：

| 节点 | 作用 | `deps` | 输入规则 |
| --- | --- | --- | --- |
| `collect-a` 至 `collect-e` | 五个独立调查 Agent | 无 | 接收任务初始输入，五个节点并行 |
| `summarize` | 汇总调查结果 | `collect-a` 至 `collect-e` | 运行时从五个成功结果中选择一至多个 `inputRefs` |
| `validate-a`、`validate-b` | 两个独立校验 Agent | `summarize` | 两个节点都消费 `summarize` 的结果，并行校验 |
| `report` | 生成最终报告 | `summarize`、`validate-a`、`validate-b` | 消费汇总结果和两个校验结果；配置 `final_report: true` |

一次运行的后端轨迹如下：

1. `hexa-api` 创建 `Run R1001`，绑定 `WorkflowRevision 7`，保存 Agent、模型、提示词和工具配置快照。五个 `collect-*` 节点进入 `queued`，随后进入 `running`。
2. 五个节点分别创建 `NodeRun` 尝试并行执行。假设最终都成功，五个节点变为 `succeeded`，各自保存独立输出版本 `O-a` 至 `O-e`。此时 `summarize` 的依赖已满足，但 Run 进入 `waiting_human`，因为它需要人工决定实际引用哪些结果。
3. 后端追加保存人工决定 `D1001`：选择 `O-b` 和 `O-d`。这次决定不修改 `WorkflowRevision 7`，而是成为 `Run R1001` 的运行数据。继续执行时，`summarize` 的 NodeRun 输入清单固定为 `inputRefs = [O-b, O-d]`，不会把另外三个结果传入上下文。
4. `summarize` 成功后保存输出 `O-s`。`validate-a` 和 `validate-b` 的依赖同时满足，两个节点并行执行，分别保存输出 `O-va` 和 `O-vb`。
5. `report` 在三个输入都成功后执行，输入清单固定为 `[O-s, O-va, O-vb]`，生成产物 `A-report-1`。由于该节点配置了 `final_report: true`，Run `R1001` 进入 `completed`，Task 进入 `completed`，当前结果指针指向 `A-report-1`。
6. 任务详情读取的是后端保存的 Run 和 NodeRun 记录，因此可以展示完整时间线：五个并行节点、一次人工决定、一个总结节点、两个并行校验节点和最终报告。刷新页面或重新打开任务不会重新执行 Agent。

这个例子中的关键约束是：`deps` 决定节点何时可以执行，`inputRefs` 决定节点实际消费哪些结果；人工选择只改变本次 Run 的输入清单，不改变已保存的工作流版本。

工作流图可以表达并行、串行、条件等待和人工门控。用户在运行过程中可以修改布局；影响执行语义的修改必须先暂停或取消活动运行，再保存新的工作流版本。

## 系统边界

### 组件职责

| 组件 | 职责 |
| --- | --- |
| `client` | 展示任务和运行状态；编辑画布并提交 API 请求；展示错误、加载、恢复、结果和调试信息；不保存任务权威状态，不执行 Agent，不自行推进状态 |
| `hexa-api` | 认证、任务权限、Task/Workflow/Template/Run/NodeRun 持久化；状态转换；工作流校验；运行调度；人工决定；结果引用；调试数据脱敏；向 client 提供 REST/SSE API |
| Gateway | 接收 `hexa-api` 发起的 Agent 执行请求并返回执行结果；不保存 Hexa 任务、工作流或运行历史 |
| 数据库 | 保存任务定义、工作流版本、模板版本、运行记录、节点尝试、结果引用和审计信息 |

本 Change 不修改 Gateway 的任务模型和 `/v1/workflow-tasks`，也不把 Gateway 作为任务状态的权威来源。

### 产品对象

| 对象 | 职责 | 可变性 |
| --- | --- | --- |
| `Task` | 用户可见的任务身份、当前工作流版本、当前结果指针和任务状态 | 标题、描述、布局和当前版本指针可修改 |
| `WorkflowRevision` | 一份完整且不可变的节点图、依赖、输入声明和节点配置 | 创建后不可修改 |
| `Template` | 可复用的模板身份 | 可创建新版本 |
| `TemplateVersion` | 一份不含运行态数据的工作流定义 | 创建后不可修改 |
| `Run` | 绑定一个 `WorkflowRevision` 的一次执行 | 状态追加推进，历史不可覆盖 |
| `NodeRun` | Run 中一个节点的一次执行尝试、输入、输出、日志和错误 | 追加记录，不覆盖旧尝试 |
| `Artifact` | 节点或任务产生的文件、报告或结构化产物 | 按版本保存，受任务权限保护 |

不新增 `Team` 模型。“多个 Agent 一起执行”是工作流中的并行节点关系；协作成员和团队权限属于后续独立需求。

## 状态契约

### NodeRun 状态

节点状态属于某个 Run，不属于全局 Task：

`idle` → `ready` → `queued` → `running` → `succeeded` / `failed` / `skipped` / `canceled`

- `idle`：依赖或输入条件尚未满足。
- `ready`：依赖已满足，等待调度。
- `queued`：已进入执行队列。
- `running`：正在调用 Agent。
- `succeeded`：产生可用输出。
- `failed`：执行失败或结果不确定，不自动重放外部副作用。
- `skipped`：按用户操作或节点策略跳过。
- `canceled`：运行取消时尚未完成的节点。

`stale` 不是持久化状态，而是当前结果视图的派生标记：当节点当前采用结果引用的上游版本已经变化，旧结果显示为“过期”。历史 NodeRun 不被改写。

### Run 状态

`pending`、`running`、`waiting_human`、`completed`、`failed`、`canceled`。

- `pending` → `running`：通过启动预检后开始调度。
- `running` → `waiting_human`：到达人工门控，等待用户决定。
- `waiting_human` → `running`：用户提交合法决定，继续同一个 Run。
- `running` → `completed`：所有必需节点成功或按策略跳过。
- `running` / `waiting_human` → `canceled`：用户取消，未完成节点标记为 `canceled`。
- `running` → `failed`：出现无法继续的失败。

终态 Run 不重新打开。终态重跑创建新的 Run，并保留旧 Run。

### Task 状态

`draft`、`running`、`waiting`、`completed`、`failed`、`archived`。

- `draft`：没有活动运行，任务可编辑。
- `running`：存在 `pending` 或 `running` Run。
- `waiting`：存在 `waiting_human` Run，或阶段运行完成但任务仍需用户继续编排。
- `completed`：最终报告节点成功，或用户主动结束任务。
- `failed`：最近一次 Run 失败且没有活动 Run。
- `archived`：用户归档，不能编辑和运行；取消归档后恢复为归档前状态。

最终报告节点使用配置字段 `final_report: true` 标识，不根据节点名称推断。任务完成后默认只读；重新打开后进入 `draft`，保存新 WorkflowRevision 后才能再次运行。

## 工作流与人工操作

### 两种结果选择方式

**预先声明的人工门控**用于固定流程：工作流版本中预先声明门控节点、候选输入节点和选择规则。Run 到达门控后进入 `waiting_human`，用户选择一个或多个结果。选择作为 Run 内追加的人工决定保存，继续请求将选中结果固化到下游 NodeRun 的输入清单，不修改 WorkflowRevision。

**事后改图续编**用于用户看完阶段结果后再决定下一步：用户拖入总结、校验或报告节点，保存新的 WorkflowRevision，创建新的 Run，并显式引用旧 Run 中有效的结果。旧 Run 和旧快照保持不变。

两者不能混用：前者是运行时决定，后者是新的工作流版本。

### 依赖和结果引用

- `deps` 表示节点执行依赖，决定何时可以运行。
- `inputRefs` 表示节点实际消费哪些结果，决定传入下游 Agent 的上下文。
- 等待五个节点完成但只选择其中两个结果时，五个节点都在 `deps` 中，只有两个结果进入 `inputRefs`。
- 每个结果引用必须包含来源 Task、Run、节点、NodeRun 尝试和输出版本。
- 运行开始后，实际输入清单固化；后续编辑或当前结果指针变化不改变历史输入。
- 失败、删除、无权限或已过期结果不能作为默认有效输入；用户显式确认使用旧版本时，必须记录该决定。

### 重试、跳过和采用

- 活动 Run 中失败或取消的节点可以追加 NodeRun 尝试，沿用该 Run 的 WorkflowRevision 和配置快照。
- 终态 Run 中重跑节点创建 `kind=rerun` 的新 Run，原 Run 不改变。
- 新输出默认是候选结果。用户点击“采用为当前结果”后，Task 的当前结果指针才更新，并记录审计事件。
- 当前结果指针变化后，实际依赖旧结果的下游结果显示为 `stale`，需要重新执行才能恢复有效。
- “忽略”只在节点配置允许跳过时可用；依赖被忽略输出的节点必须有明确的缺失输入策略，否则保持等待或失败并展示原因。

## 数据和安全规则

- Run 创建时，`hexa-api` 预检所有将执行节点的 Agent、模型、提示词、工具和配置版本，并将执行所需配置摘要写入 Run 快照；不保存密钥、授权头或 API Key。
- 配置不可用时，启动请求失败并列出节点；执行中配置失效时节点失败，不静默切换 Agent 或模型。
- 调试数据写入数据库前脱敏，读取时再次按字段过滤；敏感请求头、凭据和授权信息永不进入 client 响应。
- 任务、模板、Run、NodeRun 和 Artifact 按当前 `hexa-api` 的用户与工作区范围检查权限。client 提供的用户或工作区字段不能作为授权依据。
- 默认不自动清理运行记录，提供显式删除任务能力。删除时删除任务私有记录；共享 Artifact 只有在没有其他引用时才删除实际文件。
- 限制：每个 WorkflowRevision 最多 50 个节点、200 条边；单节点输出最多 1MB；单个 Run 最多 500 次 NodeRun 尝试。时间线和调试接口必须分页，超大输出返回摘要和受保护的产物引用。
- 单个任务同一时间最多一个活动 Run。重复创建、继续、重试和采用请求使用幂等键；同一键不同请求内容返回冲突。

## API 约定

所有接口位于 `/api/hexa`，需要现有 `hexa_session` Cookie。

### 任务和工作流

- `POST /tasks`：创建空白任务或从 `template_version_id` 创建任务。
- `GET /tasks`：分页返回任务列表、Task 状态和最近 Run 摘要。
- `GET /tasks/{task_id}`：返回任务、当前 WorkflowRevision、当前结果指针和最近运行信息。
- `PUT /tasks/{task_id}/workflow`：携带 `expected_revision` 保存新 WorkflowRevision；版本冲突返回 409。
- `POST /tasks/{task_id}/state`：执行 `reopen`、`finish`、`archive`、`unarchive` 等用户状态动作。

### 运行和节点

- `POST /tasks/{task_id}/runs`：创建 Run；支持结果复用和 `Idempotency-Key`。
- `GET /tasks/{task_id}/runs`：分页返回 Run 历史。
- `GET /runs/{run_id}`：返回 Run、NodeRun 状态和阶段结果。
- `GET /runs/{run_id}/events`：通过 SSE 推送运行状态变化。
- `POST /runs/{run_id}/continue`：提交人工决定并继续 `waiting_human` Run。
- `POST /runs/{run_id}/pause`、`POST /runs/{run_id}/cancel`：暂停或取消运行。
- `POST /runs/{run_id}/nodes/{node_id}/retry`、`POST /runs/{run_id}/nodes/{node_id}/skip`：执行节点控制。
- `POST /tasks/{task_id}/nodes/{node_id}/adopt`：采用某次 NodeRun 输出为当前结果。
- `GET /node-runs/{node_run_id}`：返回脱敏后的调试详情。

### 模板

- `GET /templates`、`POST /templates`：列出或创建模板。
- `POST /templates/{template_id}/versions`：创建不可变模板版本。
- `POST /tasks/{task_id}/save-as-template`：用任务当前 WorkflowRevision 创建模板版本。

接口返回结构化错误码，例如 `revision_conflict`、`active_run_exists`、`invalid_transition`、`input_ref_unavailable`、`configuration_unavailable`、`idempotency_conflict` 和 `storage_limit_exceeded`。错误消息面向用户，日志保留内部关联 ID，不能泄露凭据或内部堆栈。

## 验收

- **AC-1 统一任务入口：** 空白创建和模板创建都进入 `/tasks/{id}`，模板历史运行结果不被复制。
- **AC-2 画布编辑：** 用户可以编辑节点、依赖、输入映射和布局；保存生成不可变 WorkflowRevision；活动 Run 中语义配置锁定。
- **AC-3 并行执行：** 五个无依赖 Agent 可以并行运行，运行状态和节点状态通过 API/SSE 更新。
- **AC-4 结果选择：** 用户可以选择五个并行结果中的一个或多个作为总结节点输入，`deps` 与 `inputRefs` 语义正确。
- **AC-5 阶段编排：** 总结、校验和报告节点可以按依赖顺序继续执行，最终报告节点成功后任务完成。
- **AC-6 人工门控：** Run 进入 `waiting_human`，用户提交选择后继续，历史决定可追溯。
- **AC-7 运行历史：** 多次 Run 互不覆盖，每次 Run 保存 WorkflowRevision 快照，每个 NodeRun 保留输入、输出、错误和尝试历史。
- **AC-8 节点控制：** 重试、跳过、取消和终态重跑符合状态契约；终态重跑创建新 Run。
- **AC-9 结果采用：** 采用新结果后，实际消费旧结果的下游结果显示为过期，历史记录仍可查看。
- **AC-10 调试：** 节点检查器可查看脱敏输入、执行环境、输出、错误、耗时和重试历史。
- **AC-11 模板：** 模板版本只包含工作流定义，不包含任务运行记录、结果和密钥。
- **AC-12 权限和安全：** 不同用户或工作区不能读取、引用或导出无权访问的任务结果；敏感信息不进入持久化和响应。
- **AC-13 可靠性：** 版本冲突、活动 Run 冲突和重复请求有明确错误；API 进程恢复后不自动重放不确定的 Agent 副作用。
- **AC-14 响应式界面：** 桌面和移动视口下任务列表、画布、检查器、运行区、加载、失败和恢复状态可用。

未纳入本版本：Team/成员权限、外部队列和多实例调度、跨设备离线编辑、复杂条件分支、Artifact 长期存储扩展、旧 `/v1/workflow-tasks` 迁移。
