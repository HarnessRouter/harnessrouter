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

### 版本关系与保存边界

本节为任务、模板、运行记录和画布查看布局的开发契约，适用于客户端、应用后端、测试和评审。需求确认日期：2026-11-18。这里规定目标行为，不代表当前客户端演示数据或本地模板草稿已经完成后端接入。

对象关系如下：

```text
Template → TemplateVersion
                └── 显式使用模板创建 Task
Task → WorkflowRevision
          ├── Run A → NodeRun / Artifact
          └── Run B → NodeRun / Artifact
```

服务端 API 使用以下稳定身份表达这些关系：Task 暴露当前 `WorkflowRevision` 的 ID 和不可变版本号；Run 同时固定 `workflow_revision_id`、兼容保留版本号，并在 `execution_snapshot` 中保存执行时的工作流、输入、Agent 配置和来源版本。任务创建时的模板来源固定为 `source_template_id`、`source_template_version_id` 和来源版本号。客户端可以保留本地编辑草稿，但只有服务端返回的 WorkflowRevision 才是 `saved` 状态，Run 只能引用已保存版本，不能引用草稿。

- “我的任务”展示具体工作事项 `Task`；“运行记录”展示任务的一次执行 `Run`。一个任务可以有多个工作流版本和多条运行记录，一个 Run 固定属于一个 Task 并绑定一个 WorkflowRevision。
- 使用模板创建任务时，固定记录来源模板 ID 和模板版本 ID，并建立任务自己的工作流定义快照；仅复制可复用定义，不复制历史 Run、NodeRun、结果、产物或凭据。允许从空白创建无来源模板的任务。
- 任务与来源模板之间是版本来源关系，不是持续同步关系。模板新增版本不会自动升级旧任务；任务改动也不会自动写回来源模板。

| 用户操作 | 保存对象 | 版本及影响边界 |
| --- | --- | --- |
| 编辑任务中的节点、依赖、输入声明或 Agent/模型等执行配置 | 当前任务的工作流草稿 | 草稿修改不创建模板版本，不改变既有 Run |
| 点击保存任务流程 | 新的不可变 WorkflowRevision | 更新该 Task 当前工作流版本；不覆盖旧工作流版本，不创建或更新 TemplateVersion |
| 启动任务或终态后再次运行 | 新的 Run | 固定绑定启动时已保存的 WorkflowRevision 和执行配置快照；不得隐式运行未保存草稿 |
| 点击“保存为模板” | 新 Template 的初始版本；或用户明确指定的现有 Template 的新版本 | 必须是独立、显式操作；使用选定且已保存的 WorkflowRevision，仅保存可复用定义，不覆盖已有模板版本 |
| 在模板设计器点击保存新版本 | 新的不可变 TemplateVersion | 更新模板的当前版本指针；不改变由旧版本创建的任务或历史运行 |
| 在运行记录中拖动节点、平移、缩放、切换查看布局 | 客户端视图状态 | 仅调整查看方式，不创建 WorkflowRevision 或 TemplateVersion，不改写 Run 快照或 NodeRun |
| 重放运行记录 | 无业务数据写入 | 按历史事件回看，不重新执行 Agent，不创建 Run |

保存为模板默认创建新模板。只有用户明确选择目标模板时才能为该模板追加版本；不能仅凭任务的来源模板关系自动选中并写回原模板。存在未保存的任务草稿时，应提示先保存任务流程，再选择该版本保存为模板；保存失败时保留草稿和错误提示，不显示成功。

每次运行必须保存工作流版本和执行配置快照。运行记录的流程图使用该 Run 绑定的快照，禁止使用 Task 当前工作流或模板最新版本重新拼装历史图。运行状态、事件、节点尝试和输出随执行追加记录；已经固定的定义、配置和历史尝试不得被后续任务编辑覆盖。

同一任务的两次 Run 如果绑定不同 WorkflowRevision，节点和依赖结构可以不同；绑定同一个版本时定义结构保持一致，但节点状态、重试、输出和运行时人工决定可以不同。运行时人工决定仍遵循下文“工作流与人工操作”，不隐式生成模板版本。

运行记录的节点位置覆盖按 Run 隔离，当前仅作为页面内临时状态，刷新或切换运行记录后恢复该运行的默认布局。以后若增加本地布局记忆，也必须与工作流定义、运行快照分别存储。活动运行中的查看布局可调整；执行语义修改仍遵循状态契约，通过新的 WorkflowRevision 和新的 Run 生效。

任务 Artifact 只保存 Gateway 文件的不可变引用和任务权限元数据。Hexa 不复制 Gateway 文件内容；读取和下载必须经过 hexa-api 的任务权限检查与服务端代理。Artifact 归属于单一 Task、Run 和 NodeRun，不能作为其他任务的输入或被其他工作区读取。远端清理按 Artifact 逐项记录 `active`、`cleaned` 或 `cleanup_failed`，失败项允许安全重试。

界面必须区分“保存任务流程”“保存为模板”“保存模板新版本”“运行”“重放”，不能用一个保存动作隐式执行多种业务写入。任务应显示来源模板及固定版本（或无来源模板），运行记录应显示所属任务及绑定工作流版本，并支持返回所属任务。

开发验收必须覆盖以下场景（对应 AC-1、AC-2、AC-7、AC-11、AC-14）：

1. 从模板 v1 创建任务，模板发布 v2 后旧任务的来源和流程仍保持 v1 的快照。
2. 修改并保存任务流程只产生该任务的新 WorkflowRevision；模板内容、模板版本数量和其他任务均不改变。
3. 同一任务先后按工作流 v1、v2 创建 Run A、B；重新打开 A 仍展示 v1 图，B 展示 v2 图，历史输入输出和尝试保持可查。
4. 显式保存为新模板成功后才出现新模板；显式选择现有模板时只追加新版本，旧版本和既有任务不改变；保存失败保留草稿，未保存草稿不能被静默发布为模板。
5. 模板版本只含可复用定义，不包含运行记录、结果、产物内容或密钥；终态再次运行创建新 Run，重放不产生执行请求。
6. 拖动运行节点后连线同步更新，平移、缩放和重放正常；无业务写入请求、无定义版本递增，切换运行记录不串用位置覆盖，刷新恢复默认布局。

## 状态契约

### 静态 DAG 并发上限

静态 DAG 已支持并行和普通依赖汇合，不新增 ParallelNode。工作流定义可设置顶层 `max_concurrency`，严格接受 1 至 50 的整数（不接受布尔值、字符串、小数和 null）；省略时使用 50，与单工作流最多 50 节点及原有并行能力兼容。非法值在创建任务、保存工作流、保存模板和运行预检时按 `invalid_workflow` 返回 422，不产生新版本或执行请求。

并发上限是工作流执行配置，随 WorkflowRevision 和 Run 的 workflow 快照固定。旧工作流和历史 Run 未携带该字段时按 50 解释，不补写历史定义。不改变 `deps`（调度依赖）和 `inputRefs`（实际消费结果）的关系。

首批实现保留当前批次调度：按已保存节点顺序选择最多 `max_concurrency` 个可执行 Agent 节点，同时调用 Gateway，等待本批全部完成后重新计算依赖。没有选中的节点保持 `idle`，不提前标记 running、占用启动时间或发起 Gateway 请求；已确认的显式人工节点不占 Agent 调用名额。运行取消或暂停后不派发下一批；失败节点的必需下游不执行，不因上限而将人工门控或容量等待误判为 Run 结束。

本上限只约束单 Run 的节点派发，不表示全局限流、Runtime/MCP 工具并发限制或 Workspace 写入隔离。后续分别实施工作区隔离、恢复收据、结构化条件分支、有界 foreach/repeat；当前仍拒绝 DAG 回边，不允许运行中修改 WorkflowRevision。

### 声明式条件分支

节点可以声明固定格式的 `condition`，用于在静态 DAG 中选择分支：

```json
{
  "source": "route",
  "path": "decision.next",
  "op": "eq",
  "value": "fast"
}
```

`source` 必须是当前节点的 `deps` 之一；`path` 只能由点分隔的对象字段组成；`op` 目前只允许 `eq`、`neq`、`in`、`exists`。`eq` 和 `neq` 对字段值做 JSON 值比较，`in` 要求 `value` 为数组，`exists` 只判断字段是否存在且不接受 `value`。条件值来自 source 节点成功输出的脱敏 JSON；条件不是 Python、JavaScript、模板或任意表达式，服务端不执行用户提供的代码。

条件节点必须先等待全部 `deps` 满足。条件不匹配时，NodeRun 追加为 `skipped`，错误原因固定为 `condition_not_matched`，不调用 Gateway，也不占用并发名额。条件匹配时按普通 Agent 或人工节点规则执行。历史 Run 只使用启动时保存的条件定义和节点输出，不读取当前工作流。

条件分支的汇合节点必须在工作流中显式设置 `allow_missing_inputs: true`，并允许其 `deps` 中出现 `skipped` 节点；运行时上下文只包含成功的 `inputRefs`。没有该声明的汇合节点不会把跳过当作成功依赖，保持等待或进入无法继续的失败状态。条件只负责选择静态节点，不新增动态节点、不修改依赖、不允许回边，也不实现 `foreach`、`repeat` 或运行中改图。

### 有界重复

节点可以声明有界 `repeat`，用于让同一个静态节点根据自身输出追加执行尝试：

```json
{
  "max_iterations": 3,
  "until": { "path": "done", "op": "eq", "value": true }
}
```

`max_iterations` 必须是 `1..10` 的整数；`until` 只允许 `eq` 或 `exists`，路径使用与条件分支相同的安全字段路径规则。每次重复仍使用原节点 ID，并追加一个 `NodeRun`，其 `attempt` 递增；旧尝试、输入、输出和错误不可覆盖。`until` 在该次尝试成功后读取脱敏输出判断。匹配后节点保持该次 `succeeded`，下游才可继续；未匹配且尚有配额时追加下一次 `idle` 尝试。

达到 `max_iterations` 仍未匹配时，最新尝试变为 `failed`，错误码为 `repeat_limit_exceeded`，Run 不得继续执行依赖该节点的下游。重复只是在静态节点上的有界尝试，不形成 DAG 回边，不生成新节点，不允许运行中修改上限，也不代表全局重试策略。进程恢复不会自动重放不确定的外部副作用；只有已明确成功且输出可判断的尝试才会进入下一轮。

### 有界 foreach

节点可以声明有限集合展开：

```json
{
  "source": "collect",
  "path": "items",
  "max_items": 10
}
```

`foreach.source` 必须是当前节点的 `deps` 之一，`path` 使用条件分支相同的安全字段路径，`max_items` 必须是 `1..10` 的整数。集合只从 source 节点的成功输出读取；缺少路径或值不是 JSON 数组时，节点失败并使用 `foreach_input_invalid`；数组超过上限时，节点失败并使用 `foreach_limit_exceeded`；空数组产生 `{"items": []}`，不调用 Gateway。

每个集合项调用一次 Agent，复用同一节点 ID，并以独立 `NodeRun.execution_kind=foreach_item` 和 `foreach_index` 标识项；`attempt` 只表示该项自身的执行尝试，不再承担集合索引。串行模式按索引逐项调用；并行模式最多同时派发工作流 `max_concurrency` 个集合项。所有项成功后追加不可变的 `execution_kind=foreach_aggregate` NodeRun，输出聚合为 `{"items": [输出...]}`，下游只看到聚合记录；任何项失败都会停止后续派发并使展开节点失败。正在运行的项取消或进程恢复时逐项记录 `canceled` 或 `interrupted_unknown_outcome`，不能只更新展开节点的汇总状态。

foreach 是固定数量的节点执行，不创建新的工作流节点、不修改 DAG、不形成回边、不支持嵌套 foreach 或无限展开。集合和 `max_items` 随 Run 快照固定；运行中修改工作流不会影响当前展开。`mode` 只允许 `serial` 或 `parallel`。

### 有界跨节点循环

节点可以声明一个固定节点集合组成的循环体：

```json
{
  "body": ["work", "check"],
  "max_iterations": 3,
  "until": { "source": "check", "path": "done", "op": "eq", "value": true }
}
```

循环检查节点的 `loop.body` 必须是已存在的静态节点列表，并包含自身；循环体不能与 `repeat` 或 `foreach` 同时启用。每轮循环只追加这些固定节点的 NodeRun，循环体内部保持原有依赖顺序；终止条件从指定循环体节点的成功输出读取。满足条件后释放下游，未满足且仍有配额时开始下一轮；达到 `max_iterations` 后检查节点以 `loop_limit_exceeded` 失败，不再派发下一轮。

循环不会创建新节点、修改 WorkflowRevision 或允许任意 DAG 回边。循环体、上限和终止条件随 Run 快照固定。取消、恢复和调试按每轮 NodeRun 保留历史；运行中的不确定 Agent 副作用不自动重放。

### 编排配置界面

任务与模板编辑器共用结构化配置：工作流级最大并发数；节点级条件来源（仅前置依赖）、字段路径、固定比较操作和值；允许缺失输入；以及单次、repeat、foreach 三选一执行模式。repeat 与 foreach 互斥，显式人工节点仅使用单次模式。比较值支持 JSON 值，普通文本按字符串保存；`in` 必须输入 JSON 数组；`exists` 不保存 value。非法路径、来源或上限在保存时定位错误，保留草稿且不发送请求。

编辑已保存工作流、保存模板、协调器创建任务及重新打开编辑器时必须保留顶层并发配置和节点配置。删除依赖或节点时同步移除以其为来源的 condition/foreach，避免保存悬空引用。运行详情从 Run 固定快照显示配置、当前尝试、集合项编号和跳过/上限错误原因，不以 Task 当前配置替代历史。桌面与 390px 窄屏均能滚动访问配置和保存入口。

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

显式 `node_type: human` / `human_gate` 节点同样属于人工门控，即使未设置 `requires_human` 也必须停在 `waiting_human`，不会调用 Agent 或自动标记成功；只有用户提交合法输入引用后，才在同一 Run 中确认该节点并继续调度。

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

## Agent 能力、插件与权限审批

### 能力来源和快照

任务节点可以引用 Agent 的工具、Skill、MCP Server 和 UHP Plugin。能力来源必须保留为
`direct`、`plugin`、`builtin` 或 `runtime`，不能在保存任务时把不同来源压平为一个无来源的工具列表。

Gateway 已发布的 UHP `2026-10-19` Plugin 子协议是插件包和运行时组合的唯一来源。插件包继续使用
`plugin.json`、`mcp.json` 和 `skills/<name>/SKILL.md`；Hexa 不重新定义插件包格式，也不复制插件文件、认证头、凭据或
插件内部脚本。Harness 直接配置与启用插件派生的 MCP/Skill 分开保存；`enabled=false` 的插件仍可被列出但不进入有效运行
配置，`skipped` 组件必须进入启动诊断，名称冲突和不支持的 transport 必须在配置或预检阶段显式失败。

Run 启动预检必须从 Gateway 读取并固化能力组合摘要：插件名称、版本、manifest/package/content digest、来源、启用状态、
`skipped`、直接和插件派生的 MCP/Skill/Tool、disabled tools、UHP discovery 能力及有效组合 digest。快照可以保存引用、版本、
摘要和哈希，不能保存密钥或可还原的 secret。运行中的 Gateway 解析、sandbox、`PLUGIN_ROOT`、`PLUGIN_DATA` 和 stdio
containment 仍由 Gateway/Runner 负责；Hexa 只负责任务策略、预检、快照、审计和用户可见结果。

Skill 只能声明其所需能力，不能授予权限。插件安装或启用也不能绕过任务、工作区、Agent 或 Runtime 的限制。

### 有效权限

每次工具执行的有效权限按以下交集计算，并在 Run 快照中保留决策摘要：

```text
EffectivePermission
  = WorkflowPolicy
    ∩ WorkspacePolicy
    ∩ AgentPolicy
    ∩ RuntimeNativePolicy
    ∩ CurrentApproval
```

工具风险至少区分 `read_only`、`workspace_read`、`workspace_write`、`local_process`、`network_read`、`external_write`、
`credential_access`、`destructive` 和 `permission_change`。任何一项原生拒绝都不能被人工批准抬高。工具审批是一次精确调用的
授权，不是给 Agent、Plugin、Skill 或 MCP Server 永久授予权限。

### 运行时审批和 UHP 扩展边界

现有 `input_required/input_response` 只表示 Agent 向用户请求输入，现有 `function_call` 事件只表示执行进度；二者都不能
作为副作用发生前的精确工具授权边界。需要审批的调用必须在 Gateway 派发工具前创建持久化的
`tool_approval_request`，绑定 `command_id`、精确参数或服务端参数引用、工具来源、能力/策略 digest、`request_hash` 和
过期时间。审批记录、决定、执行回执和 `side_effect_state` 必须可在断线或重启后读取；`unknown` 结果必须要求 reconciliation，
不得盲目重放。

本 Change 只提交 `protocol/proposals/tool-approvals/` 的本地规范草案，不修改已发布的 UHP schema、Gateway discovery 或
现有运行代码。草案以 UHP `2026-10-19` 为基线，采用新增能力和新增 item/error 的兼容扩展；只有 Gateway 的前置拦截、持久化
恢复、Runner 原生执行约束和 conformance suite 一起实现后，才能发布新的日期版本并宣称支持。Gateway 不具备指定策略的审批
覆盖时，Hexa 必须在 Run 启动前返回配置不可用，不能提交任务后再根据流事件推断“已经审批”。

## 当前编排边界

本 Change 已完成静态 DAG 编排的第一阶段：无依赖节点可以按 `max_concurrency` 并行，条件分支使用固定比较对象，repeat 是
同一静态节点的有界重复，foreach 是有限集合的串行或并行展开；任务和模板编辑器可保存这些配置，Run 使用不可变快照显示实际尝试、
项索引和跳过原因。

当前仍明确不支持并行 foreach、嵌套 foreach、跨节点循环、DAG 回边、无界循环、动态节点生成、运行中改图和并发项的部分聚合。
这些能力需要另行定义项级并发、失败重启、顺序/聚合、租约和恢复语义，不能通过把现有 `max_concurrency` 直接套到集合项上来
推断。工具审批也不因本轮编排 UI 完成而自动可用。

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
- `GET /runs/{run_id}/nodes`：分页返回该 Run 的节点尝试摘要。
- `GET /tasks/{task_id}/artifacts`、`GET /runs/{run_id}/artifacts`、`GET /node-runs/{node_run_id}/artifacts`：分页返回有权访问的 Artifact 元数据。
- `GET /artifacts/{artifact_id}`、`GET /artifacts/{artifact_id}/content`：读取或通过 hexa-api 服务端代理下载 Artifact。

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
- **AC-15 静态 DAG 并发上限：** 通过任务 API 保存 `max_concurrency=2` 的五个独立 Agent 和汇总节点，运行期间最多两个 Agent 调用活动且至少两个可同时执行，汇总等待全部必需依赖完成；非法值返回 422；取消阻止后续批次；失败不触发其下游；人工门控仍需合法决定；重开后修改配置不改变历史 Run 快照。省略上限仍支持五节点并行。
- **AC-16 声明式条件分支：** 条件只允许固定比较对象且来源必须是依赖节点；未匹配分支记录为 `skipped/condition_not_matched` 且不调用 Gateway；匹配分支正常执行；显式 `allow_missing_inputs` 汇合节点等待所有依赖完成并只消费成功输入；任意表达式、未知来源、非法路径和不支持操作返回 422。
- **AC-17 有界重复：** `repeat.max_iterations` 只接受 1 至 10 的整数，`until` 只接受安全的 `eq`/`exists` 条件；重复追加同一节点的 NodeRun 尝试并递增 `attempt`，终止条件满足后下游执行；达到上限仍未满足时记录 `repeat_limit_exceeded` 并阻断下游；不会生成动态节点或无限派发。
- **AC-18 有界 foreach：** `foreach.source` 必须是依赖节点，`max_items` 只接受 1 至 10 的整数；数组逐项产生同一节点的 NodeRun 尝试并按 `foreach_index` 保序聚合，全部完成后下游只收到聚合结果；空数组不调用 Gateway；缺少数组和超限数组分别返回 `foreach_input_invalid`、`foreach_limit_exceeded`；不创建动态节点或无限展开。
- **AC-19 并行 foreach：** `foreach.mode=parallel` 产生独立的项级 NodeRun，项索引不复用 `attempt`；同一 Run 同时执行的集合项不超过 `max_concurrency`，所有成功项按索引聚合到独立 aggregate NodeRun；单项失败、取消和恢复都保留逐项状态，不能覆盖已完成项输出；非法 mode 返回 422。
- **AC-20 有界跨节点循环：** 固定 `loop.body` 只能引用当前节点和已声明依赖，且包含检查节点；每轮按静态依赖顺序追加 NodeRun，终止条件满足后释放下游，达到上限记录 `loop_limit_exceeded`；不生成动态节点、不接受无界循环或任意回边。

分页接口保留原有资源数组字段，并返回 `pagination.offset`、`pagination.limit` 和 `pagination.has_more`。任务、Run、Run 节点、NodeRun 尝试、模板和 Artifact 列表均不得要求客户端一次性读取无界历史数据。

工作台搜索名称或 ID、按状态筛选时，服务端先执行权限和筛选再分页。`GET /runs` 提供当前工作区跨任务运行记录，按 Run ID 倒序且仅返回有权访问的任务运行；任务详情和运行深链独立读取，不依赖列表中已经加载该对象。模板响应提供独立的 `latest_version`，不以历史版本首批末项推断最新版本。用户点击下一页或加载更多才读取追加页；失败保留已加载数据，查询或工作区变化后不接受旧响应。本批验收沿用 AC-7、AC-10、AC-11、AC-12、AC-14，覆盖跨页搜索、运行隔离、旧版本保留、追加页重试和移动端可操作性。

未纳入本版本：Team/成员权限、外部队列和多实例调度、跨设备离线编辑、复杂条件分支、旧 `/v1/workflow-tasks` 迁移。Artifact v1 继续由 Gateway 托管文件内容，不复制到 Hexa 本地对象存储。
