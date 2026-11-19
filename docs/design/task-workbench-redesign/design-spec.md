# Hexa 任务作战台设计规范

- 版本：v1.4
- 日期：2026-11-18
- 状态：已实施，生产 UI 与设计稿对齐
- 范围：我的任务、任务详情/人工确认、运行记录、模板管理、对话，以及移动端关键状态
- 总览图：[`task-workbench-board.png`](task-workbench-board.png)

## 1. 设计目标

任务页不是“工作流编辑器的附属列表”，而是用户处理工作的主界面。设计把“需要人介入的事项”放在最前，并在同一屏内同时呈现：

1. 现在需要做什么。
2. 为什么需要我。
3. 已有结果和下一步动作。
4. 这次运行的证据与历史。

整体方向命名为“任务作战台”：保持 Hexa 现有应用壳和冷静的产品气质，用更清晰的优先级、更完整的运行证据和更直接的决策界面替代当前扁平表格与大面积空白。

## 2. 设计来源

| 来源 | 使用方式 |
| --- | --- |
| 用户需求（2026-11-17） | 重新设计当前任务相关页面，参考成熟产品与既有设计规范，生成设计图 |
| [`CHG-task-centric-workflow/spec.md`](../../changes/CHG-task-centric-workflow/spec.md) | Task → WorkflowRevision → Run → NodeRun、人工门控、`deps` / `inputRefs`、模板与状态契约 |
| [`CHG-task-centric-workflow/visual-contract.md`](../../changes/CHG-task-centric-workflow/visual-contract.md) | 三段式任务详情、候选结果、右侧检查器、运行时间线、移动端断点与可访问性要求 |
| 当前实现截图（`.artifacts/task-redesign/current/`） | 识别现网问题：任务列表信息稀疏、运行页被画布占满、模板页缺少决策信息 |
| Linear | 紧凑表格、侧边预览、克制的状态语言、搜索与筛选 |
| GitHub Actions / Vercel | Run 身份、阶段进度、执行轨迹、事件日志的组织方式 |
| n8n / Dify / LangSmith | DAG 画布 + 节点检查器 + 运行态节点状态 |
| Temporal | 事件溯源式 Run 时间线、`waiting_human` 状态与可追溯人工决定 |
| Notion / Attio | 记录预览、属性摘要、最近活动和上下文动作 |

本设计只参考信息层级与交互模式，不复制品牌视觉，不引入新的 Cloud、部署、上传、余额、密钥握手或 hosted provider 入口。

## 3. 页面清单

| # | 场景 | 源文件 | 设计图 |
| --- | --- | --- | --- |
| 01 | 我的任务 | [`01-tasks-overview.html`](01-tasks-overview.html) | [`screens/01-tasks-overview.png`](screens/01-tasks-overview.png) |
| 02 | 任务详情 / 人工确认 | [`02-task-detail.html`](02-task-detail.html) | [`screens/02-task-human-review.png`](screens/02-task-human-review.png) |
| 03 | 运行记录 | [`03-runs.html`](03-runs.html) | [`screens/03-run-history.png`](screens/03-run-history.png) |
| 04 | 模板管理 | [`04-templates.html`](04-templates.html) | [`screens/04-template-library.png`](screens/04-template-library.png) |
| 05 | 移动端我的任务 | [`05-mobile-tasks.html`](05-mobile-tasks.html) | [`screens/05-mobile-tasks.png`](screens/05-mobile-tasks.png) |
| 06 | 移动端人工确认 | [`06-mobile-detail.html`](06-mobile-detail.html) | [`screens/06-mobile-human-review.png`](screens/06-mobile-human-review.png) |
| 08 | 对话 | [`08-chat.html`](08-chat.html) | [`screens/08-chat.png`](screens/08-chat.png) |
| 01b | 我的任务 · 扩展栏收起 | [`01-tasks-overview.html`](01-tasks-overview.html) | [`screens/01-tasks-overview-collapsed.png`](screens/01-tasks-overview-collapsed.png) |

可复用的应用壳、图标和缩略流程图位于 [`design-kit.js`](design-kit.js)，视觉 token 与组件样式位于 [`styles.css`](styles.css)。

### 3.1 主工作区布局

“我的任务”“运行记录”“模板管理”保留现有 64px rail 与 248px 上下文侧栏，并在主工作区内做全高 master-detail：

- 左侧列表列占剩余宽度，列表从主工作区顶部开始，不再重复页面标题和关注条。
- 顶部筛选工具条直接承担过滤；下方是单一 table，不插入状态或日期分组行。
- 表头、数据行和底部分页状态共同铺满整列高度；数据行按可用空间等分，最后一行贴底，不留卡片尾部空白。
- 我的任务、运行记录和模板管理的详情扩展栏共用同一宽度规则：1440px 视口下展开宽度为 720px，均从 `y=0` 贯穿到 `y=900`，通过 1px 分隔线与左侧连续。更窄桌面宽度下按 `clamp(400px, 64%, 720px)` 收缩，并保证列表列至少保留 280px；运行页内部再分为执行轨迹与实时事件两列。
- 三页详情栏都支持拖拽左边缘调整宽度；各页分别记忆当前宽度，窗口变窄时收敛到可用范围，窗口恢复后不丢失原值。收起后为 44px 把手，再次展开恢复该页记忆宽度。
- 三页列表都提供“列表 / 卡片”切换。卡片上方为工作流缩略图，下方为标题、状态/进度和元数据；切换到卡片后选中项继续与右侧详情同步。
- 页面级搜索与筛选位于 table 工具条；详情操作和收起入口位于右侧栏顶部。
- 收起后扩展栏变为 44px 唤起把手，列表自动扩展；再次展开恢复对应宽度。
- 任务详情、运行记录和模板管理沿用同一规则：右侧检查器/详情面板从工作区顶部贯穿到底部，形成稳定的全高分栏。

## 4. 信息架构

### 4.1 应用壳

- 64px 深色主导航：任务、对话、智能体、应用。
- 248px 上下文侧栏：工作区、新建任务、我的任务、运行记录、模板库（管理页），以及最近访问、待处理提示。
- 主工作区：桌面内容宽度 1064px，外边距 32px。
- “新建任务”保留空白创建与模板创建的产品语义，不在首屏恢复 Cloud 能力。

### 4.2 我的任务

- 单一 table，不按状态或日期分组；全部、待我处理、运行中、已完成等范围由顶部筛选条切换。
- 列表顶部只保留范围筛选、搜索和筛选入口；当前待确认事项由首行状态与右侧扩展栏共同表达，不再增加重复横幅。
- 行内信息：任务名、Run 身份、当前阶段说明、状态、进度、最近活动。
- 列定义为任务、状态、进度、最近活动；列表铺满主列高度，任务行弹性拉伸，底部分页状态贴底显示。
- 右侧扩展栏：任务身份、Run 进度、候选结果数量、已选输入、工作流缩略图、最近活动、`deps` / `inputRefs` 说明、继续处理按钮；栏头提供页面操作和收起入口。
- 设计意图：用户不打开详情也能判断“为什么现在需要我”。

### 4.3 任务详情 / 人工确认

- 页头：任务名、等待确认状态、Run / Workflow / 时长、运行记录与取消入口。
- 阶段条：并行调查 → 人工确认 → 汇总 → 双重校验 → 最终报告。
- 左侧画布：五个并行调查节点汇聚到人工门控，再连接汇总、校验 A/B 与报告。
- 右侧检查器：五个候选输出、勾选状态、内容摘要、来源节点、时延、输出版本与查看入口。
- 流程图操作：选择等待中的人工节点后，运行属性面板复用候选结果选择器；人工节点明确标注“不会调用 Agent”，可直接确认并继续或终止任务。
- 右侧检查器从工作区顶部贯穿到底部，与左侧画布和底部时间线同屏，不随页面标题下移。
- 任务结果：详情内直接展示已采用结果与最近运行各节点输出；运行输出标注 `Run #N · Workflow vN` 和“只读快照”，按节点去重，未采用输出不写入 `current_result`。
- 工作流入口：`查看流程图` 在“我的任务”内展开 `任务流程图`，使用最近一次运行快照；`返回任务详情` 回到原详情，`查看运行记录` 仅作为次级入口，侧栏不切换到运行记录。从未运行的任务显示只读结构预览和“尚未运行”。
- 底部时间线：运行开始、五个节点完成、进入人工确认、用户选择更新。
- 关键约束：`deps` 已满足不代表所有输出都会进入下游；只有勾选结果成为 `inputRefs`。

### 4.4 运行记录

- 顶部筛选：全部、等待确认、运行中、已完成、失败；支持任务名或 Run ID 搜索，不使用日期分组。
- 单一 table 列：运行、状态、节点进度、耗时、开始时间。
- 右侧运行详情：Run 身份、状态、四项关键指标、执行轨迹、已选输入、实时事件流。
- 右侧运行详情为全高面板，事件流与执行轨迹在纵向上获得完整空间。
- 事件流使用等宽标识，如 `run.waiting_human`、`node.collect-e.succeeded`、`decision.updated`，便于排障和复制。
- 视觉重点从“无限画布”转为“这次运行发生了什么”，避免 1440×900 下仅有浮动画布控件。

### 4.5 模板管理

- 顶部筛选：全部、调查、产品、内容、风险；支持模板名搜索与新建模板。
- 单一 table 列：模板、分类、版本、结构、使用、更新。
- 详情面板展示模板结构、阶段组成、人工门控、最近使用与安全说明。
- 详情面板从页面顶部贯穿到底部，表格区只占左侧内容列。
- 明确“模板只包含工作流定义，不包含运行记录、结果文件或密钥”。
- 模板入口仍然通向任务创建，不复制历史运行结果。

### 4.6 对话

- 上下文侧栏承载工作区、新建对话、搜索与按日期归档的对话历史；当前会话高亮。
- 主线程从顶部会话身份开始，不重复页面大标题；消息、运行卡片、关键发现和人工确认按时间顺序排列。
- Run 卡片只摘要节点结果与状态，完整轨迹通过“查看完整运行轨迹”进入运行记录。
- 人工确认块与任务详情使用同一套 `inputRefs` 语义：标出已选调查结果，并提供“在任务中查看”和“确认并继续”。
- 右侧上下文栏固定展示 Agent、模型、运行环境、关联任务、引用文件、工具能力、本轮统计、最近工具调用和上下文预算。
- 右侧上下文栏可收起为 44px 把手；对话输入区固定在底部，主线程独立滚动。
- 对话页不展示部署、上传到 hosted provider、余额或密钥入口；附件说明明确数据留在当前工作区。

## 5. 视觉规范

### 5.1 颜色

| Token | 值 | 用途 |
| --- | --- | --- |
| `--rail` | `#0b1220` | 主导航背景 |
| `--navy` | `#0f172a` | 深色强调与标题 |
| `--bg` | `#f6f7f9` | 主工作区背景 |
| `--surface` | `#ffffff` | 面板与卡片 |
| `--ink` | `#111827` | 主文字 |
| `--ink-2` | `#344054` | 次级标题 |
| `--muted` | `#667085` | 辅助文字 |
| `--line` | `#e4e7ec` | 1px 分隔线 |
| `--blue` | `#2563eb` | 主操作、运行中、当前焦点 |
| `--blue-soft` | `#eff4ff` | 蓝色浅底与选中背景 |
| `--amber` | `#f79009` | 等待人工、需要关注 |
| `--green` | `#12b76a` | 成功、已完成 |
| `--red` | `#f04438` | 失败、取消 |
| `--purple` | `#7a5af8` | 模板分类辅助色 |

颜色不是唯一状态信号；所有状态同时提供文字和图标/圆点。

### 5.2 字体

- 字体栈：`Segoe UI Variable / Segoe UI / Microsoft YaHei UI / Microsoft YaHei`。
- 页面标题：25–28px，650。
- 任务与面板标题：12–21px，650。
- 正文和行描述：10.5–12px。
- 辅助元数据：8–10px；运行事件标识使用等宽字体。
- 数字和 Run ID 使用等宽字体，减少跳动并提升可扫描性。

### 5.3 间距与几何

- 8px 基础网格；常用间距 4 / 7 / 8 / 12 / 14 / 16 / 18px。
- 圆角：小控件 7–9px，面板 12px，大卡片 12–16px，移动端底部面板 20px。
- 主面板使用 1px hairline border，阴影克制，不使用重渐变。
- 桌面点击目标不小于 28–36px；移动端主要按钮不小于 34px，底部导航整块可点。
- 画布节点、检查器候选和任务行都保留清晰 hover / selected / waiting 状态。

## 6. 状态与内容

| 对象 | 需要覆盖的状态 |
| --- | --- |
| Task | `draft`、`running`、`waiting`、`completed`、`failed`、`archived` |
| Run | `pending`、`running`、`waiting_human`、`completed`、`failed`、`canceled` |
| NodeRun | `idle`、`ready`、`queued`、`running`、`succeeded`、`failed`、`skipped`、`canceled` |
| 页面 | loading、empty、error、permission denied、revision conflict、active run exists |

设计图中的关键状态：

- 任务：等待确认、运行中、已完成、草稿。
- Run：等待人工、运行中、失败、已完成、已取消。
- 人工确认：已选 2 / 5，其余候选保持未选。
- 模板：已选中、可复用、最近使用和只读说明。

实施时应补充加载骨架、空列表、读取失败、保存冲突与恢复提示；这些状态不改变本规范的空间结构。

## 7. 响应式

### 7.1 断点

| 视口 | 行为 |
| --- | --- |
| `>= 1280px` | 完整三段式应用壳；管理页使用 table + 全高详情；对话使用主线程 + 全高上下文栏 |
| `901–1279px` | 保留两级导航与全高分栏；三页详情统一按 `clamp(400px, 64%, 720px)` 收缩并保证列表至少 280px，筛选组独占工具条首行，列表按容器宽度渐进隐藏耗时/进度列，不产生内部横向溢出 |
| `<= 900px` | 隐藏上下文侧栏和固定详情分栏；列表占满主区，详情和会话上下文通过右侧抽屉打开 |
| `<= 640px` | 单个 table 行改为两行摘要布局；对话上下文使用固定抽屉；composer 固定在主线程底部 |

### 7.2 移动端

- 我的任务：顶部筛选 + 单一表格列表；点选任务打开右侧详情抽屉，不挤压列表。
- 运行记录：点选 Run 打开详情抽屉，流程图继续由详情中的“打开流程图”进入。
- 模板管理：点选模板打开详情抽屉，编辑与使用入口保留在抽屉内。
- 对话：主线程占满主区，顶部“上下文”按钮打开会话检查器抽屉；输入区始终位于视口内。

## 8. 可访问性

- 所有图标按钮带明确可访问名称，如“搜索任务”“更多任务操作”“预览日志取证输出”。
- 状态不只依赖颜色，使用圆点、图标与文本共同表达。
- 桌面可读文本目标不低于 9px，主体正文保持在 10.5px 以上；移动端关键正文不低于 8px 的视觉稿基准。
- 选中行、当前节点、等待门控使用边框、背景或 ring 形成非颜色冗余信号。
- 保留角色化命名：任务列表、任务详情、运行状态画布、运行流程图、节点检查器。
- 键盘焦点使用 3px 蓝色半透明 ring；按钮、任务行和候选结果均可操作。
- 动画仅用于状态过渡；支持 `prefers-reduced-motion: reduce`。

## 9. 实施映射

以下映射已落地到当前客户端；运行、模板和任务数据仍沿用现有前端样例与编辑器行为，不改变权威状态来源。

| 设计区域 | 现有实现位置 | 落地说明 |
| --- | --- | --- |
| 应用壳与侧栏 | `client/src/AppBackendClient.tsx`、`client/src/styles.css` | 采用 64px rail + 248px 上下文侧栏；移除重复的运行记录子列表 |
| 我的任务 | `client/src/AppTasks.tsx` 的 `mine` section | 列表/卡片双视图、顶部范围/搜索/时间筛选、1440px 下 720px 全高详情（窄桌面按 `clamp(400px, 64%, 720px)` 收缩并保证列表至少 280px）、可拖拽宽度和 44px 收起把手；任务行按可用高度拉伸，列表铺满至底部状态栏 |
| 任务详情 | `client/src/AppTasks.tsx`、`client/src/ApiTaskWorkbench.tsx`、`client/src/workflow-canvas.tsx` | 全高检查器承载进度、候选输入、工作流和最近活动；运行流程图继续为次级视图；选中等待中的人工节点后，右侧运行属性直接提供上游结果选择、确认并继续和终止任务，不调用 Agent |
| 运行记录 | `client/src/AppTasks.tsx` 的 `runs` section | 列表/卡片双视图，筛选栏换行适配窄列表列，详情在 1440px 下为 720px、窄桌面按同一宽度规则收缩；轨迹与实时事件双列保留，详情可拖拽，流程图入口保留 |
| 模板管理 | `client/src/AppTasks.tsx`、`client/src/AppModules.tsx` | 列表/卡片双视图 + 同规则可拖拽全高详情；分类计数由模板数据计算，筛选完整可见，编辑器保留版本与返回语义 |
| 对话 | `client/src/AppBackendClient.tsx`、`client/src/ChatInspector.tsx` | 主线程与 304px 上下文栏同级全高；桌面收起为 44px 把手，移动端使用上下文抽屉 |
| 状态和错误 | `client/src/app-api.ts`、`client/tests/app-ui/*` | 结构变化同步更新目标断言；保留 Agent、消息、附件和恢复失败提示 |

实施边界：

- 不改变 Task / Run / NodeRun 的权威状态来源；前端不自行推进状态。
- 人工确认只改变本次 Run 的 `inputRefs`，不修改 WorkflowRevision。
- 活动 Run 中锁定 Agent、提示词、模型、工具、依赖、输入引用和门控配置。
- 不恢复 Cloud 部署、上传、目标工作区、账号余额、密钥握手或 hosted provider 能力。

## 10. 渲染与证据

### 10.1 设计原型

原型为本地 HTML/CSS/JS，不依赖外部网络资源。使用 Chromium 在 Windows 上按 CSS 视口渲染，`deviceScaleFactor = 2`。

| 文件 | CSS 视口 | 输出像素 | SHA-256 |
| --- | --- | --- | --- |
| `task-workbench-board.png` | 2400 × 3000 | 3600 × 4500 | `48a3425b8bc5d807fa2828e6b07c0c1816eabf2af6266b369d4302904a152486` |
| `screens/01-tasks-overview.png` | 1440 × 900 | 2880 × 1800 | `4c3ce248ed2d7d1515d4a7c73cc6f915305829af4f31f8266eeb8c75f45c7cfe` |
| `screens/01-tasks-overview-collapsed.png` | 1440 × 900 | 2880 × 1800 | `495722f67a69d748a231a18bbfd569331824bffcb3b60fb9633ba2ee71206813` |
| `screens/02-task-human-review.png` | 1440 × 900 | 2880 × 1800 | `7ebf7fb0d33a0ba1c67134bb38b0ca09e4ce27a3b584dfbde7fcaeb0b4454e64` |
| `screens/03-run-history.png` | 1440 × 900 | 2880 × 1800 | `941b961cdb4c000fb30d9a3eb91f09f5f17d1004f04e0220f833dcea25155aa7` |
| `screens/04-template-library.png` | 1440 × 900 | 2880 × 1800 | `4056871a543e8becacfb1828d104e1ab20b5cdae1acdd301258c9b653f997d08` |
| `screens/05-mobile-tasks.png` | 390 × 844 | 780 × 1688 | `58a778920b43b1be0cb3c320185dce3c5d150eb70f3f72499cef6a277ec23fae` |
| `screens/06-mobile-human-review.png` | 390 × 844 | 780 × 1688 | `321509c0a1ec5d3a368e164f6f7645ef59f24f844859d4e208ab0b7177b9e87e` |
| `screens/08-chat.png` | 1440 × 900 | 2880 × 1800 | `16ba2fdfad08a1cd7daa6c8f6f85d866877b32f3e4fbfc3e9201f70d058e6999` |

渲染检查结论：

- 桌面页面在 1440×900 内无横向滚动和任务内容溢出。
- 我的任务从主工作区顶部直接进入筛选与列表，8 条任务铺满列表高度，最后一行贴合底部状态栏。
- 任务详情扩展栏与任务列表同高，从 `y=0` 贯穿到底部；收起后保留 44px 把手并释放列表宽度。
- 任务详情检查器、运行详情和模板详情均从工作区顶部贯穿到底部，与左侧内容保持连续分栏。
- 三页详情在 1440px 下均使用 720px 宽度；我的任务、运行记录和模板管理都支持拖拽左边缘调整，并各自记忆宽度。运行记录详情内部保持左侧执行轨迹、右侧实时事件双列；更窄桌面宽度下按 `clamp(400px, 64%, 720px)` 收缩并保证列表至少 280px，列表渐进隐藏耗时/进度列以保持可读。
- 移动端列表完整显示到最近任务；底部导航不覆盖最后一张卡片。
- 移动端人工确认的候选勾选、选中底色和固定主按钮可见。
- 运行页在 1440×900 下同时保留 Run 列表、执行轨迹和事件流，不再出现只剩浮动画布控件的情况。

### 10.2 生产实现证据

生产页面使用 Playwright + Chromium/Edge 在 Windows 上按 1440×900、1280×900、1024×900 与 390×844 实际渲染；截图目录为 `docs/screenshots/task-workbench-redesign/`。

| 页面 | 文件 | SHA-256 |
| --- | --- | --- |
| 我的任务 | `app-tasks-overview.png` | `ee50f5714cbe5a2321dc4ea05fe20de60e6e8fe630be886aeffc7dcd236fd9ae` |
| 运行记录 | `app-runs.png` | `e3d1a57d429cacf316aceaa0b0676a2ccc64e928c0d3d2151aa3396b7c05bbae` |
| 模板管理 | `app-templates.png` | `cef94931a500098a24665a646aa50f0f78d4c73a16a661a8f8f7d9a9e0e2a0b6` |
| 对话 | `app-chat.png` | `5f1c79ba6f475c9a917413f5e53bcd75a14ac996cc7e100180690afe3362e6cf` |
| 移动端我的任务 | `app-tasks-mobile.png` | `f26439bc9ae63fd6a9e05520817a582987f468172e32be4d80cab8ca145077b3` |
| 移动端对话 | `app-chat-mobile.png` | `b5d496e0d28c718a298d4bb02898253e3cbe7d36cdfbe5344a63118a7dabf6ab` |
| 我的任务卡片 | `app-tasks-cards.png` | `c43c348664a2db0e1132d05f81b0be2ca71401ba5e1e76c6dda2a0d52f143240` |
| 运行记录卡片 | `app-runs-cards.png` | `60ab328d9688dd08b77a469c8d0be667f0c24cd056339ac25a1f9d0e6f0ac1eb` |
| 模板管理卡片 | `app-templates-cards.png` | `da0cf317b4e7e3cde620166bc828e95c6089cc2517558ec2dc5dfc31ea7a8f38` |
| 运行流程图状态 | `app-run-graph-states.png` | `4eab3198c5cd1783bd2a6b741f42b6943e5ea6b03db3356fc7c4b4a01283e1ea` |
| 任务详情最近运行结果 | `app-task-detail-direct.png` | `aa84851badb245d29299d61dc5813a90d5b04faf22bce27c4116f3adf6fd8720` |
| 任务流程图原位打开 | `app-task-flow-direct.png` | `298e01b56dcf0433779ee990d732ed3442593d626e7bc146a9c7a3c68d10b130` |

## 11. 尚未评估

- 真实 Gateway、Provider 和持久化 Task/Run 数据下的完整链路：`not_evaluated`，本轮以应用 API 契约夹具和现有前端样例数据验收页面行为。
- Windows 以外的字体渲染差异未在本机验证；需在目标平台补验。
- 真实长文本、超长任务名、50 节点工作流和大输出场景未在生产页面截图覆盖。
- 加载、空状态、错误、权限不足和版本冲突沿用现有提示，本轮未生成专用视觉基线。

## 12. 下一步

1. 接入真实 Task / Run / Template 数据后，复核筛选、选中同步、运行恢复和详情字段映射。
2. 在目标非 Windows 平台补验字体、换行和固定分栏几何。
3. 为 loading、empty、error、权限不足和版本冲突建立补充截图基线。
4. 如后续新增 Task / Run 操作，继续沿用全高分栏和 44px 收起把手，不恢复浮层检查器。
