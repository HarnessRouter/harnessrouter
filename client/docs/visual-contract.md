# Hexa Client UI 视觉契约与审查记录

## 流程图内人工节点操作（2026-11-19）

- 设计来源与状态：用户反馈“人工节点怎么操作”；沿用任务工作台 v1.4 的运行属性、人工确认和状态色契约，明确人工节点不调用 Agent。
- 交互：在任务详情点击“查看流程图”后，选择人工节点，右侧“运行属性”显示“人工节点 · 不会调用 Agent”；用户可勾选已完成的上游结果，直接点击“确认并继续”或“终止任务”，不必跳转运行记录。
- 视觉与可访问性：人工确认区域使用等待状态的琥珀色提示块，候选结果保留节点状态与可展开输出；区域、候选复选框和操作按钮均有语义名称，忙碌时禁用重复提交。
- 自动验收：`tasks.spec.ts` 新增流程图选中人工节点、勾选上游结果并发送 continue 的用例；Chromium 目标用例 2/2、Edge 任务工作台回归 13/13，`npm run typecheck` 通过。
- 结论：通过。人工节点的选择、确认、终止路径在流程图属性面板内闭环，任务详情原有人工确认入口保持兼容。
- 未评估：真实 Gateway 持久化下的人工节点长输出、移动端抽屉内的多候选滚动和高频状态刷新。

## 任务详情直达最近运行结果与流程图（2026-11-19）

- 设计来源与状态：用户反馈任务列表应能直接查看流程图和任务结果，不必先跳转运行记录；沿用 design-spec v1.4 的任务详情、结果快照与流程图视觉，不改变 Task / Run 版本与保存语义。
- 结果：任务详情“任务结果”同时展示已采用结果和最近运行各节点输出；运行输出标注 `Run #N · Workflow vN` 与“只读快照”，与已采用节点按 `nodeId` 去重，未采用输出不进入 `current_result`，也不改变结果状态。
- 流程图：工作流区块新增“查看流程图”，在“我的任务”内打开“任务流程图”区域，使用所选任务最近一次 `RunSnapshot`；`返回任务详情` 回到原详情，“查看运行记录”保留为次级入口，侧栏选中项始终为“我的任务”。
- 草稿与边界：从未运行的任务显示只读工作流结构预览和“尚未运行”，不伪造节点状态；无 Run 时不展示“查看运行记录”。
- 自动验收：`tasks.spec.ts` 新增最近运行输出、流程图原位打开、侧栏不跳转和草稿预览用例；`task-workbench.test.mjs` 新增 `latestRunOutputs` 过滤空输出和空 Run 用例。Edge 目标集 12/12、Chromium 全量 42/45；3 项失败为既有 Agent/导航用例（`agents.spec.ts:81`、`agents.spec.ts:113`、`navigation.spec.ts:102`），与本改动无关，串行复跑仍失败，记录为既有问题。客户端单测 33/33，`npm run typecheck`、`npm run build` 通过（仅既有 >500kB chunk advisory）。
- 截图与哈希（1440×900，Chromium）：`docs/screenshots/task-workbench-redesign/app-task-detail-direct.png` `AA84851BADB245D29299D61DC5813A90D5B04FAF22BCE27C4116F3ADF6FD8720`，展示任务详情中的“最近运行节点输出”只读快照；`app-task-flow-direct.png` `298E01B56DCF0433779EE990D732ED3442593D626E7BC146A9C7A3C68D10B130`，展示“任务流程图”在“我的任务”内打开及返回入口。
- 结论：通过。任务结果和流程图可在任务页闭环查看，未采用结果不会误写为已采用，也未引入运行记录跳转。
- 未评估：真实 SSE 高频更新时结果与快照的刷新连续性、超长节点输出和移动端流程图操作。

## 任务卡片单列塌缩与流程图状态动态（2026-11-18）

- 设计来源与状态：用户反馈任务页卡片状态样式在窄列/单列时错位，并要求流程图按节点状态增加动态效果；沿用 design-spec v1.4 的卡片、状态色与 reduced-motion 约束，不改变业务状态语义。
- 结构：卡片网格使用 `grid-auto-rows: max-content` 与顶部对齐，卡片高度随内容增长，不再被等高行压缩后裁掉标题行；缩略图按可用宽度等比缩放并居中，单节点与多节点卡片保持接近的节点尺寸。
- 状态样式：卡片顶部 2px 状态条和缩略图背景分别使用蓝/橙/绿/红语义色；任务、Run 状态点的运行中状态使用呼吸动画；任务列表卡片、运行记录卡片和模板卡片共用同一套状态表达。
- 流程图动态：任务详情缩略图与运行快照按节点状态渲染 succeeded/running/queued/failed/canceled/idle 色调；运行中节点有 ring 呼吸，运行中连线虚线流动；已完成链路使用绿色实线，就绪链路蓝色呼吸，失败链路红色虚线，待执行链路灰色虚线。箭头颜色与连线一致。
- 可访问性与降级：所有动效仅为状态过渡，`prefers-reduced-motion: reduce` 下统一关闭；状态同时保留文字与圆点，不只依赖颜色。
- 自动验收：新增 `task-cards.spec.ts` 覆盖 1440/1280/1024/900/390 单列塌缩、卡片内容不越界、缩略图不溢出、状态色调与动画、reduced-motion 关闭；先确认旧实现失败后修复。新增 `node and edge tones` 单测覆盖色调映射。
- 验证结果：Chromium `task-cards` 4/4，全量 `app-ui` 44/44；Edge `task-cards` + `workbench-redesign` 8/8；客户端单测 31/31；`npm run typecheck` 与 `npm run build` 通过（仅保留既有 >500kB chunk advisory）。
- 截图与哈希：`docs/screenshots/task-workbench-redesign/app-tasks-cards.png` `C43C348664A2DB0E1132D05F81B0BE2CA71401BA5E1E76C6DDA2A0D52F143240`；`app-runs-cards.png` `60AB328D9688DD08B77A469C8D0BE667F0C24CD056339AC25A1F9D0E6F0AC1EB`；`app-templates-cards.png` `DA0CF317B4E7E3CDE620166BC828E95C6089CC2517558EC2DC5DFC31EA7A8F38`；`app-run-graph-states.png` `4EAB3198C5CD1783BD2A6B741F42B6943E5EA6B03DB3356FC7C4B4A01283E1EA`（均为 1440×900 Chromium）。
- 结论：功能与视觉通过；卡片在单列和窄列下不再裁切，流程图状态可区分且动态克制。
- 未评估：真实 SSE 高频更新下的动画连续性、非 Windows 字体渲染和超长节点名称。

## 智能体二级导航详情页（2026-11-18）

- 设计来源与状态：用户要求智能体页面的二级导航在点击某个智能体后，右侧显示详情页，内容层级参考 Gateway 的 Agent 设置：Instructions、Agent harness、Capabilities、Memory、Environment & limits。
- 结构：二级导航中的智能体项改为选择态，不再直接新建对话；主区域在选中后显示全宽详情卡片，顶部为名称、运行时、模型、Memory 摘要和“返回列表 / 开始对话 / 删除”，主体为 220px 层级导航与详情面板。未选中时保留原有 Agent 卡片列表。
- 内容：Instructions 显示系统提示词与字符数；Agent harness 显示智能体 ID、名称、运行时、默认模型、Reasoning effort 和创建时间；Capabilities 显示 Skills、MCP servers、Disabled tools、Plugins 及计数；Memory 显示状态、名称、引擎、范围、原因、Observe 和 Provisioned；Environment & limits 显示环境变量、请求头、最大步数、超时和绑定环境。
- 数据边界：字段来自 `GET /api/hexa/agents` 返回的 Gateway harness 记录，同时兼容 camelCase 与 snake_case。缺失字段显示“Gateway 未返回”，不以空值或演示值冒充；环境变量只展示名称及“已保存的引用 / 已设置（值已隐藏）/ 空值”，不渲染值本身。
- 交互：点击二级导航智能体或 Agent 卡片进入详情；点击“模板库”清除选择并返回模板列表；“返回列表”回到 Agent 卡片；详情内“开始对话”沿用既有会话 Agent/模型锁定与路由。层级导航使用 `role="tablist"`、`role="tab"`、`role="tabpanel"`，支持方向键、Home、End 切换。
- 响应式：980px 以下层级导航改为横向可滚动标签，640px 以下详情头与操作按钮纵向排列；390px 视口无页面横向溢出。
- 自动验收：新增 `agent-detail.test.mjs` 覆盖 camelCase、snake_case、缺失字段、Memory 关闭/原因和敏感环境变量引用；新增 Playwright 用例覆盖二级导航进入详情、五个层级内容、敏感值不显示、390px 无横向溢出和“开始对话”返回会话页。结果：客户端单测 30/30，Chromium `agent-templates` 3/3、`agents` 3/3、`navigation` 5/5，Edge 详情用例 1/1；`npm run typecheck` 与 `npm run build` 通过（仅保留既有 >500kB chunk advisory）。
- 截图与哈希（Chromium，1440×900 / 390×844）：`docs/screenshots/agent-detail-desktop.png` `19D6170F7CB8DE87265C9FD9E6212018FA69B05A68E6577D5D5BE09B9FB6EC9C`；`docs/screenshots/agent-detail-mobile.png` `01FC7675C5B0203251A28E599740B3641D135E1575CB0671FF233358C40FFA17`。
- 结论：功能与视觉通过。详情页层级、选中态、只读字段和响应式布局符合目标。
- 未评估：真实 Gateway 中缺少字段、超长 Instructions、数百项 Capabilities 以及受限权限 Agent 的线上组合；当前由单元测试和受控接口夹具验证字段映射与边界。

## 对话滚动条贴分栏与可拖拽上下文宽度（2026-11-18）

- 设计来源与状态：用户截图要求对话滚动条靠近会话区与上下文栏之间的分割线，并让分割线支持拖动调整右侧上下文栏宽度。
- 结构：会话主列增加全宽 `.chat-scroll` 滚动容器，正文 `.chat` 仍保持 820px 最大宽度居中；滚动条固定在会话主列右缘，与上下文栏分隔线相邻。上下文栏左侧新增 `role="separator"` 拖拽手柄。
- 交互：拖动手柄向左扩大上下文栏、向右缩窄；支持 `ArrowLeft` / `ArrowRight` 每次 24px 调整，`Home` / `End` 跳到最小 / 最大宽度。宽度范围 280–560px，且始终为会话区保留至少 420px；宽度持久化到 `localStorage['hexa.chat.context-width']`，刷新后恢复。640px 以下隐藏手柄，继续使用固定上下文抽屉。
- 消息层级：用户气泡保留浅色底、细边框和圆角，但移除阴影；Agent 回复使用 30px 头像、独立名称/模型行和 8px 行后间距，Markdown 正文从同一列开始，不再使用卡片边框、底色或内边距。代码块、表格等内部元素仍保留各自的局部容器；输入 composer 继续保留轻微抬升。
- 可访问性：手柄名称为“调整上下文宽度”，提供垂直方向、最小 / 最大 / 当前宽度，并有清晰焦点环；拖动期间使用列调整光标并禁止文本选择。
- 自动验收：新增用例断言滚动容器右缘与上下文栏左缘对齐，拖动后上下文栏增宽且滚动条仍贴分栏线，键盘调整生效，刷新后宽度保持；同时断言用户气泡 `box-shadow` 为 `none`，回复正文无边框、无内边距、背景透明，Agent 头像位于名称左侧，名称与正文左对齐且正文下间距不少于 7px。Chromium 全量 `app-ui` 39/39，Edge 对话 4/4；`npm run typecheck` 与 `npm run build` 通过。
- 截图与哈希：`docs/screenshots/chat-scroll-divider-resize.png` `BA63654107D494520447D467AFF3A0001DECFA748EEBE4BD25D145E082463409`，1440×900 Chromium，展示长对话、贴分栏线滚动区域、拖宽后的上下文栏和带头像/元信息行的回复正文。
- 短回复消息头：`docs/screenshots/chat-message-header.png` `B7CE0BDFD3CAFC18BB99789AC284BCB2A47255EDBAD48DA862C5188EC78046EC`，1440×900 Chromium，展示头像、Agent 名称、模型标签与正文的层级关系。
- 结论：通过。分栏线拖拽和滚动区域边界符合目标；构建仅保留既有大 chunk advisory。

## 对话长内容滚动修复（2026-11-18）

- 问题与复现：长回复会把 `.main` 从 720px 视口高度撑到 3019px，而外层 `.app` 保持固定高度并裁剪；`.chat` 的 `scrollHeight` 与 `clientHeight` 相等，底部内容不可达。
- 修复：主工作区 `.main` 固定为可用高度的 100%，补 `min-height: 0` 与 `overflow: hidden`；对话页同步约束高度，滚动只发生在 `.chat-thread .chat`。该滚动容器使用稳定的细滚动条、可视轨道和语义色滑块。
- 验收：新增长回复用例，先确认旧实现无法滚动并失败；修复后断言 `scrollHeight > clientHeight`、`scrollTop > 0`、底部标记进入视口，并验证可滚回首个段落。
- 回归结果：Chromium 全量 `app-ui` 38/38，Edge 对话 3/3；`npm run typecheck` 与 `npm run build` 通过（仅保留既有大 chunk advisory）。
- 截图与哈希：`docs/screenshots/chat-long-reply-scroll.png` `0E65B88289FC6CAE8526DA72371A1DCFB03AD0769F91FC8596C50F824FF6644F`，1440×900 Chromium，展示长回复滚动到底部后的末尾内容与 composer。
- 结论：通过。内容区和输入区高度稳定，长回复可完整滚动查看。

## 对话内容区 Markdown 渲染（2026-11-18）

- 设计来源与状态：用户要求只优化对话内容区，并参考 Gateway 工作台的 `TaskThread`、`CodeBlock` 能力；不改动侧栏、上下文检查器和整体布局。沿用现有白底表面、细边框、主色与等宽字体 token。
- 目标页面与视口：对话主线程；Chromium / Edge，桌面 1440×900，移动 390×844。
- 结构：Agent 回复按 GFM Markdown 渲染标题、段落、强调、列表、任务列表、引用、分隔线、图片、链接和表格；表格在自身容器内横向滚动。围栏代码块显示语言、语法高亮和复制按钮；每条完整回复提供“复制回复”。用户消息仍按原文显示，不执行 Markdown。
- 交互与恢复：流式生成内容同样按 Markdown 增量渲染并显示光标；仅当用户接近底部时自动跟随最新输出。链接在新标签打开并带 `noopener noreferrer`；原始 HTML 经 `rehype-sanitize` 过滤，不渲染脚本或外部对象。
- 视觉：标题、正文、列表与代码采用明确层级；代码卡头部与正文分离，亮暗主题分别使用语义 token；表格、行内代码和链接在窄屏保持可读。390px 下内容区无页面横向溢出。
- 自动验收：先新增 `chat.spec.ts` 用例并确认旧实现因缺少 Markdown 标题、表格和代码复制入口失败；实现后目标用例通过，`chat.spec.ts` Chromium 2/2、Edge 2/2；客户端单测 27/27；`npm run typecheck`、`npm run build` 通过；`npm audit --omit=dev` 为 0 漏洞。
- 截图与哈希：亮色 `docs/screenshots/chat-markdown-content.png` `4544DA6688B7FB1D31E8851F2CC0531221BB238F39C94F2AADBCC1036D4FB7CB`；深色 `docs/screenshots/chat-markdown-dark.png` `275D8BD9CE2FF0C2DFEE1B3A212CD99C10932EC95139D292E679EFCBFA374867`；移动端 `docs/screenshots/chat-markdown-mobile.png` `7A2073EFF9D56D4CF20B36350FA7089B96798BA4BFE05194C5EBD55EB485BD3B`。
- 结论：功能与视觉通过。构建保留既有大于 500kB chunk advisory。
- 未评估：真实 Gateway/Provider 的超长回复、超大表格与非 Windows 字体渲染。

## 全量界面回归验收（2026-11-18）

- 验收范围：客户端 `app-ui` 全部 36 条用例，Chromium 与 Edge；集成 UI 全部 10 条用例，覆盖登录、会话过期、Agent、模板、任务、运行记录、SSE、HTTP Gateway、空状态、失败恢复和移动端断点。
- 结果：Chromium `app-ui` 36/36、Edge `app-ui` 36/36；客户端单测 26/26；`npm run typecheck` 通过；`npm run build` 通过，仅保留既有大 chunk advisory。
- 集成结果：Chromium 串行 5/5、Edge 串行 5/5。首次 2 worker 并发运行出现模板数据未及时可见、Edge 上下文提前关闭和任务详情等待超时；对应失败用例逐条以 1 worker 隔离复跑全部通过，判定为 FastAPI/数据库/Edge 进程并发争用，不是可复现的界面回归。
- 验收结论：结构、交互、可访问性、内容溢出、亮暗主题、键盘焦点、`prefers-reduced-motion`、移动端输入字号和触控尺寸均通过；未发现当前样式改动引入的可复现 UI bug。
- 复验命令：`npx playwright test -c playwright.app.config.ts --project=chromium --workers=4`、`npx playwright test -c playwright.app.config.ts --project=edge --workers=2`、`npx playwright test -c playwright.integration.config.ts --workers=1`、`npm test`、`npm run typecheck`、`npm run build`。

## 视觉 Token 与任务工作台可读性校正（2026-11-18）

- 设计来源与状态：`docs/design/task-workbench-redesign/design-spec.md` v1.4 §5（颜色、字体、几何）与 §8（可访问性）；用户确认按上一轮评审的最小补丁范围推进，不修改布局和交互。
- 目标页面与视口：我的任务、运行记录、模板管理及其右侧详情；Chromium / Edge，桌面 1440×900。
- Token 真源：新增 `client/src/tokens.css` 与 `client/src/theme.ts`。亮色主色统一为 `#2563eb`，暗色主色为同色系 `#4c9dff`；Ant Design `colorPrimary`、`borderRadius` 与 CSS token 共用同一来源。亮色背景 `#f6f7f9`、主文字 `#111827`、辅助文字 `#667085`、分隔线 `#e4e7ec`、导航底 `#0b1220`，字体栈统一为 `Segoe UI Variable / Segoe UI / Microsoft YaHei UI / Microsoft YaHei`。
- 字号收敛：工作台表头 10.5px、行标题 13px、行描述 11.5px、状态 10.5px、Run ID/时间 10.5px 等宽、详情正文 11px、运行事件 10px、模板版本与最近使用 10.5px；半像素字号不再出现在任务工作台的关键信息层。
- 对比度：辅助文字从 `#98a2b3`（白底 2.58:1）与 `#a0aaba`（2.35:1）改为 `#667085`（4.97:1），次级强调使用 `#475467`（7.69:1）；表头、表尾、Run ID、行描述均满足小字号文本 4.5:1 的 AA 下限。
- 暗色表面：工作台表头/表尾、行 hover/selected、分隔线、详情提示块、运行告警、模板缩略图、状态圆点改用 `--hx-surface*`、`--hx-line`、`--hx-primary-soft`、`--hx-status-*` 等语义 token；修复暗色下仍出现 `#fbfcfd/#f7faff/#fffaeb` 亮块的问题。
- 附带修正：运行轨迹项由三列网格改为单列，避免唯一的文本列被 27px 图标列挤压成多行；测试夹具补齐 task/run artifacts 空分页响应，避免产物请求返回 `{}` 导致 `ArtifactList` 渲染异常。
- 自动验收：目标用例 `visual-tokens.spec.ts` 3/3 在 Chromium 与 Edge 通过；全量 `app-ui` Chromium 33/33 通过（`--workers=4`）；客户端单测 26/26；`npm run typecheck` 与 `npm run build` 通过（仅保留既有 >500kB chunk advisory）。8 worker 全量运行时 `chat` 与 `run-history` 各出现一次 30s 超时，单测与 4 worker 全量均通过，按并发负载波动记录为 advisory。
- 截图与哈希（1440×900，Chromium）：`client/.artifacts/task-api/visual-tokens-light.png` `0B938E14D8A56646388904850FC9E8A153C14F3CC56FB4B9069F7B6A12FACCED`；`visual-tokens-dark.png` `A255563C19B21E0C0F69E11915AAD584BD092BCA5F1872AD3DBA24D3D717B230`；`visual-tokens-dark-runs.png` `60E4800AEE6B9B35A5743B7FEE05E98CFD7ED4B6CBBEF71E187369D739B495C7`；`visual-tokens-dark-templates.png` `4CA807056EC702AE2ED93679AAC0C87EFC55282CABCECBC0FB2289DAA2BDFE93`。
- 视觉结论：通过。任务工作台在亮/暗主题下的表头、表尾、详情与运行轨迹保持可读，主色与 Ant Design 控件一致。
- 第二批落地（同一日期）：全站 `:focus-visible` 统一为 3px 主色 ring，列表行、卡片、模板节点、节点端口、详情/上下文拖拽把手、设置书签和面板都使用 `--hx-focus-ring` / `--hx-focus-ring-rail`，不再混用 2px、半透明色或 `box-shadow` 假焦点；`prefers-reduced-motion: reduce` 下全局关闭动画、过渡与平滑滚动（含工作台脉冲、流动连线与工作空间 spinner）；移动端 640px 以下输入/多行输入/下拉框统一 16px，筛选、视图切换、主操作、composer 操作和“上下文”入口不小于 34px。Ant Design 暗色 token 补齐 `colorBgContainer`、`colorBgElevated`、`colorTextBase`、`colorTextSecondary`、`colorBorder` 与 `colorBorderSecondary`，修复切换深色瞬间刷新/次要按钮白底或低对比的问题。
- 第二批自动验收：`visual-tokens.spec.ts` 6/6（Chromium 与 Edge），新增焦点环、reduced-motion、移动端输入字号/触控尺寸和暗色次要按钮对比度断言；全量 `app-ui` Chromium 36/36（`--workers=4`）；客户端单测 26/26；`npm run typecheck` 与 `npm run build` 通过（仅既有 >500kB chunk advisory）。
- 第二批截图与哈希（1440×900 / 390×844，Chromium）：`client/.artifacts/task-api/visual-tokens-light.png` `3AF5987D7253F371050FE1056FBB41CF93E24EA0B16B4FA61660FB4D4F704251`；`visual-tokens-dark.png` `6DCD9CE51E602FBA5521C16533223B41A97E8CADC8490838166C6537B05D2976`；`visual-tokens-dark-runs.png` `C829414FB5D4F83541405451E3698C487DFA7C7913F8ADECFBFC6D3774C9EF1B`；`visual-tokens-dark-templates.png` `2E8CE37C62D5E149A57660D1BF03C18958A7F189DDC2A33372815EECC26F09EB`；`visual-tokens-mobile.png` `1478140EEC35CEB1B23D907E1092517593CFE6A48CD24100DA5869A95484DF4A`。
- 视觉结论（第二批）：通过。暗色主题下工具栏次要按钮恢复深色表面与可读文字，焦点在键盘遍历时保持一致的 3px 蓝色轮廓；390px 下筛选与视图按钮增高后仍无横向溢出。
- 剩余事项：`styles.css` 分层与失效规则清理、剩余硬编码颜色逐页迁移，以及真实触控设备上的手势验证仍待后续处理。

## 任务作战台全高工作台（2026-11-18）

- 设计来源与状态：`docs/design/task-workbench-redesign/design-spec.md` v1.4，用户确认的 table/卡片 + 全高可拖拽详情和对话全高上下文栏方案。
- 目标页面与视口：我的任务、运行记录、模板管理、对话；Chromium/Edge，桌面 1440×900，中间宽度 1280×900 / 1024×900，移动 390×844。
- 结构：管理页使用顶部筛选 + table 或卡片列表 + 右侧全高 `complementary` 详情；三页详情在 1440px 下统一 720px；对话主线程与 304px 上下文栏同级全高。
- 几何：任务行按可用高度拉伸，最后一行贴合底部状态栏；三页详情在窄桌面统一按 `clamp(400px, 64%, 720px)` 收缩，最小 400px 且列表至少保留 280px，筛选独占工具条首行，列表按容器宽度隐藏耗时/进度列；详情收起为 44px 把手。
- 交互：任务/运行/模板选中同步详情；三页详情都可拖动左边缘调整、分别记忆本页宽度，并支持键盘调整；列表/卡片切换后选中项同步详情；供应商风险评估与竞品功能对比分别映射到 Run #13 / Run #15，筛选后不会落回默认 Run；运行详情保留“执行轨迹 + 实时事件”双列和“打开流程图”次级入口；模板编辑器保留返回与保存；对话 composer 始终可见。
- 响应式：900px 以下隐藏固定详情/上下文栏并通过右侧抽屉打开；390px 下页面 `scrollWidth` 保持视口宽度。
- 自动验收：工作台专项 7/7、目标集 Chromium 20/20、Edge 20/20，Chromium 全量 30/30；客户端单测 20/20；`npm run typecheck` 与 `npm run build` 通过（仅保留既有 >500kB chunk advisory）。
- 截图与哈希：`docs/screenshots/task-workbench-redesign/`，完整哈希见 `docs/changes/CHG-task-workbench-redesign/change-record.yaml`。
- 视觉结论：通过。全高分栏连续、表格铺满、筛选不截断、对话输入区可见。
- 未评估：真实 Gateway/Provider 链路、非 Windows 字体渲染、长文本和超长工作流状态。

## App-only 工作空间与设置校正（2026-11-17）

- 设计来源：用户确认的工作空间附图、设置“左侧 tab + 右侧内容”的书签式要求，以及 App-only 客户端“Gateway 由应用后端管理”的边界。
- 工作空间：左侧 rail 的工作区入口继续使用“切换工作区”可访问名称，点击后在右侧顶部展开 380px 白色圆角浮层；工作空间行为 42px 深海军蓝头像、名称/说明和当前项蓝色勾选，底部为“工作区设置”和“新建工作区”。
- 工作区表单：两个 480px 表单均使用 `centered` Modal，标题分别为“工作区设置”“新建工作区”；设置保存通过 `PATCH /api/hexa/workspaces/{id}` 更新当前空间，创建成功后自动选择新空间并刷新列表。表单失败时保留输入并显示可读错误。
- 设置：弹框标题为“设置”，桌面为 176px 左栏和右侧内容面板，左栏使用垂直书签 tab；活动 tab 为白底、细边框且右缘与内容面板左缘连续。“连接”说明 Gateway 由应用后端管理，浏览器不保存地址或 API Key；“界面与导航”提供一级导航文字开关，保存后持久化到 `localStorage`。
- 响应式：640px 以下设置 tab 改为顶部横向布局；390×844 下工作空间浮层、两个工作区表单和设置弹框均位于视口内，页面 `scrollWidth` 保持 390px。
- 可访问性：工作空间浮层为 `role="dialog"` 并使用“工作空间”名称，当前项带 `aria-current`；设置 tab 使用 `aria-selected`、`aria-controls` 和 `aria-labelledby`，支持方向键/Home/End 切换。
- 自动验收：`client/tests/app-ui/workspace-settings.spec.ts` 8/8 通过（Chromium、Edge），覆盖 380px 浮层、480px 居中表单、`PATCH` 更新、创建后自动选择、保存/创建失败保留输入、设置书签 tab、移动横向 tab 与无横向溢出；组件几何使用轮询断言，避免动画期间读取 0 宽或临时边距。
- 接口与回归：`client/tests/app-api.test.mjs` 通过（含工作空间 PATCH）、`hexa-api/tests/test_workspaces.py` 2/2、`npm run typecheck` 与 `npm run build` 通过。完整 App Playwright 本轮 30/34，通过目标工作空间/设置与导航、Agent、对话、运行历史和模板相关用例；失败项为既有的 `tasks.spec.ts` “任务菜单”内查找“运行记录”（实际入口位于二级导航）2 项，以及 1 次 Chromium 登录用例浏览器上下文超时，均与本次工作空间/设置改动无关，未修改该并行工作。
- 桌面工作空间浮层：`docs/screenshots/app-workspace-menu-popover.png`，1007×780，SHA-256 `8E8FFDF7E6B7CBEE79D3212A0E8C94242F865EBE458AFB0091B43392A0C557AA`。
- 桌面工作区设置：`docs/screenshots/app-workspace-settings-centered.png`，1007×780，SHA-256 `B5BC6BE605759A43EA96F6C94F30B9ADD3CB3EC57B7D2DC05F7F8740B92573AA`。
- 桌面新建工作区：`docs/screenshots/app-workspace-create-centered.png`，1007×780，SHA-256 `B340D8AD27D2930B2E4A27AE29C2085BC9426DCDEAD46EC82D63A0EE8F0236CE`。
- 移动工作空间浮层：`docs/screenshots/app-workspace-menu-mobile.png`，390×844，SHA-256 `5989314C319C8D9A4BAEF8F648CF24D7967A9F3BBB2EFBF1489DAD201CE62C9F`。
- 移动工作区设置：`docs/screenshots/app-workspace-settings-mobile.png`，390×844，SHA-256 `3CF2175E3E25A5B05FD8C4AAFDB49AD11208F22CAB197F95E84BC6D2AD5AFFFA`。
- 桌面设置连接页：`docs/screenshots/app-settings-bookmark-connection.png`，1007×780，SHA-256 `BCE3B7B4561695D57F250BE9762E508F306F674F121533A8E9A8E3D209288805`。
- 桌面设置界面页：`docs/screenshots/app-settings-bookmark-interface.png`，1007×780，SHA-256 `8804A23B305BB563E1B294D5A8565438CB7D5E79C40B49A4258C20E6234AEB50`。
- 移动设置界面页：`docs/screenshots/app-settings-bookmark-mobile.png`，390×844，SHA-256 `85A9FC4FAF0892BBB543F52CF7CEA96FEB0E230F482307D9AC2A3545E290D046`。
- 视觉结论：通过。工作空间浮层、两个居中表单和设置书签布局均与既有附图/要求一致；连接页不再暴露浏览器侧 Gateway 配置入口。
- 未评估：真实触控设备上的拖动与手势未单独验收；本轮使用 Playwright 的真实 Chromium/Edge 渲染和指针点击。

## 设置页书签式左侧标签（2026-11-16）

- 设计来源：用户要求“设置页面调整为左侧 tab，右侧内容，类似书签效果”；沿用工作台现有白色表面、浅灰分区、细边框和主色按钮。
- 目标页面与视口：静态客户端与应用后端模式共用设置弹框；桌面 1007×780，移动 390×844，Chromium。
- 结构：Modal 标题为“设置”，内容区为 176px 左栏与右侧内容面板；左栏使用垂直 `role="tablist"`，提供“连接”和“界面与导航”两个 `role="tab"`；右侧只渲染当前 `role="tabpanel"`，底部统一放置清除、取消和“保存设置”。
- 书签效果：活动标签采用白色表面、细边框和左侧圆角，右缘与内容面板左缘对齐并以 2px 白色覆盖接缝；左栏为浅灰底，右侧内容区与页脚保持白色。
- 交互：点击标签切换内容；`ArrowUp` / `ArrowDown` 循环切换，`ArrowLeft` / `ArrowRight` 提供同向兼容，`Home` / `End` 跳到首尾；每次打开弹框回到“连接”，关闭或取消不保存草稿。
- 响应式：640px 以下左栏改为顶部横向标签，`aria-orientation="horizontal"`；390px 视口下弹框宽 366px、左缘 12px，无横向溢出，“保存设置”位于视口内。
- 可访问性：两个标签通过 `aria-controls` / `aria-labelledby` 与面板关联，非活动标签 `tabIndex=-1`；面板可用键盘聚焦；设置开关使用可访问名称“一级导航显示文字”。
- 自动验收：先新增“settings uses bookmark-style left tabs with connection and interface panels”，旧版仍为“Gateway 连接”单页，目标弹框不存在导致 Red；实现后目标用例 Green。静态相关用例 21/21、应用后端设置相关用例 2/2（Chromium / Edge）、客户端单元测试 40/40 通过，`npm run typecheck` 与 `npm run build` 通过；构建仅保留既有大于 500kB chunk 提示。应用导航文件中并发新增的检查器标题大小写用例仍失败 2 项，与本次设置改动无关，未修改该并发工作。
- 桌面连接页：`docs/screenshots/settings-bookmark-connection.png`，1007×780，SHA-256 `62BBABC8CFE902AC3B51C5F6091F949517DBC8C32D92C721E3F4590CDACBD7AC`。
- 桌面界面页：`docs/screenshots/settings-bookmark-interface.png`，1007×780，SHA-256 `28116B7793F76FD6B9CDA85C7DF42B9C3176B2D4F36A25D336615DF1A82BE33F`。
- 移动界面页：`docs/screenshots/settings-bookmark-mobile.png`，390×844，SHA-256 `25CB6999B647CE0EF979E324BF6319FFF50B7D088C3905A12594A5EE4CE5AC75`。
- 深色界面页：`docs/screenshots/settings-bookmark-dark.png`，1007×780，活动标签底色实测 `rgb(20, 20, 20)`，SHA-256 `7F6F9DBE1E6A8DBFBF4323DFE15C793D037FCE252B0E253463E55217EF8366EB`。
- 视觉结论：通过。桌面活动标签与右侧白色面板形成连续书签轮廓，左右分区层级清楚；移动端横向标签、内容与页脚均完整可见。
- 未评估：真实触控设备上的手势切换未纳入本轮；标签切换使用点击与键盘完成，触控点击使用标准按钮行为。

## 模板编排画布与编排控件（2026-11-16）

- 设计来源：`docs/hexa-client-demo.html` 的 `templateEditorMain()`、`.org-*`、`.canvas-toolbar` 与 `templateInspector()`，对照用户截图反馈“中间画布不应被固定画布尺寸限制”。
- 目标页面与视口：Templates 编辑页；桌面 1440×900，移动 390×844。
- 结构：左侧为对话编排与节点列表，中间为无限流程画布，右侧为节点属性检查器；桌面三列同时可见，移动端按“编排 → 画布 → 属性”纵向排列且无横向溢出。
- 交互：节点可在任意方向拖出原 820×540 区域并保存坐标；空白处拖动平移；滚轮平移，`Ctrl/Meta + 滚轮` 以指针位置缩放；工具栏支持缩小、放大和适配整个流程；从右侧输出端点拖到任意节点的输入区域即可连线，并继续拦截自连、重复边和循环依赖。
- 视觉：编排标签、节点列表改用工作台自己的圆角、浅色选中态与无原生边框控件；画布为动态点阵背景，网格随平移和缩放一致移动；节点保持设计稿的 190px 白色卡片、状态点、依赖摘要和端口样式。
- 可访问性：编排标签使用 `role="tab"` 和 `aria-selected`，节点与端口保留可访问名称，连线区域保持指针操作可达；桌面画布和节点收缩在既有布局内，移动端页面宽度保持 390px。
- 自动验收：`client/tests/ui/templates.spec.ts` 9/9 通过，覆盖原生控件样式回归、越界拖动与坐标持久化、空白平移、滚轮无 passive 报错、连线与循环拦截；`client/tests/template-graph.test.mjs` 覆盖无限范围下的 `graphBounds`；完整 Playwright 28/28、单元测试 33/33、生产构建通过。
- 桌面截图：`docs/screenshots/template-infinite-canvas.png`，1440×900，SHA-256 `6A484B64942F8F5F06EBB30012C477C8E6A65680DDFF7EF158DA7F899BFC8B12`。
- 移动截图：`docs/screenshots/template-infinite-canvas-mobile.png`，390×844，SHA-256 `724804B0FC3D8CEB551166546B42254421469D24D0CE8277CA6D8FD835BD6A64`。
- 视觉结论：通过。编排控件不再出现原生按钮边框，画布不显示固定世界边界，节点、依赖箭头和点阵在平移缩放后保持一致；移动端仅通过画布内部平移大量节点，不撑开页面宽度。
- 未评估：真实触控设备上的双指缩放未纳入本轮验收；滚轮和鼠标拖拽已在 Chromium 中实测。窄屏下节点较多时仍使用适配按钮和画布平移，不额外引入移动端节点详情抽屉。

### 任务页模板设计入口（2026-11-17）

- 任务页“模板管理”不再只有静态卡片；编辑按钮和新建按钮进入同一套模板设计工作区，复用左侧对话编排、中间无限画布、右侧模板检查器。
- 设计器由任务主区域全高承载，返回按钮回到模板列表；保存新版本继续写入客户端模板草稿并保留版本递增行为，未新增 Gateway 接口。
- 桌面验收：模板列表可进入设计器，画布、节点编排和检查器同时可见；新建模板可添加节点、编辑节点名称并保存。
- 移动验收：三列工作区按编排、画布、检查器纵向排列，390×844 视口无横向溢出。
- 自动验收：`client/tests/app-ui/tasks.spec.ts` 模板入口、编辑保存和移动布局用例通过；客户端单测、类型检查和生产构建通过。

### 模板与运行记录共享画布基础组件（2026-11-17）

- 模板设计和运行记录统一复用 `client/src/workflow-canvas.tsx` 的视口、世界层、网格承载、平移和缩放基础行为。
- 模板设计保留可编辑节点、依赖校验、连线删除和模板保存；运行记录保留只读节点状态、重放控制、布局切换和运行属性栏。共享组件不持有模板或运行业务状态。
- 两个页面的画布均使用 `.workflow-canvas-viewport` 和 `.workflow-canvas-world`，节点、连线、检查器和工具栏仍由各自页面组合。
- 自动验收：任务页模板/运行记录共享 DOM 契约、模板编辑和移动布局 4/4；运行记录桌面/移动回放 2/2；客户端单测 20/20；类型检查和生产构建通过。

### 运行记录节点自由拖拽（2026-11-17）

- 运行记录沿用模板设计的节点拖拽交互。桌面端可直接拖动节点、同步移动相关依赖线；移动端保留点击节点打开属性抽屉的行为。
- 拖拽位置只属于当前运行记录画布的临时视图状态，刷新或切换运行记录后恢复布局算法位置，不修改运行快照、任务定义、运行状态或后端数据。
- 重放、暂停、节点状态、运行属性和画布平移缩放与节点自由布局互不干扰。
- 自动验收：运行记录桌面拖拽与回放、移动端属性抽屉 2/2 通过；模板设计 UI 3/3 通过；客户端单测 20/20 通过。

## 工作空间锚定浮层（2026-11-16）

- 设计来源：用户附图的工作空间切换菜单，以及现有 `ui/src/components/hrui/WorkspaceSheets.tsx`、`ui/src/components/hrui/Shell.tsx` 的工作空间语义；客户端继续只调用现有 Gateway 工作空间契约。
- 入口：左侧 rail 的工作空间按钮，使用“切换工作区”可访问名称和 `aria-haspopup="dialog"`，点击后在按钮右侧顶部对齐展开浮层，再次点击、点击外部或完成配置跳转时关闭。
- 桌面结构：380px 白色圆角浮层，工作空间行使用 42px 头像、名称说明和当前项右侧蓝色勾选；所有工作空间头像统一使用深海军蓝卡片、描边和白色首字，颜色不再承担分类含义。列表底部以分隔线过渡到“工作区设置”和“新建工作区”两个操作行。
- 子视图：选择“工作区设置”或“新建工作区”后关闭切换浮层，打开 480px 居中 Modal；设置表单编辑当前工作空间，创建表单成功后关闭弹框并自动切换到新工作空间。两个表单均保留失败输入和错误提示，并提供取消操作。
- 移动结构：浮层宽度收敛为 `min(380px, calc(100vw - 72px))`，390×844 视口下右边缘不超过视口，内容可纵向滚动且页面无横向溢出。
- 状态：未配置 Gateway、加载中、空列表、读取失败与重试、刷新失败但保留最后列表、创建/保存失败均有明确文本。
- 可访问性：浮层内容使用 `role="dialog"` 和“工作空间”可访问名称；列表项保留 `aria-current`。设置和创建弹框分别以“工作区设置”“新建工作区”命名，使用 Ant Design Modal 的焦点管理，取消、保存和关闭路径均可用键盘访问。
- 自动验收：先扩展浮层位置、白底和勾选断言，再新增“workspace settings and creation forms open as centered dialogs”，断言操作后切出浮层、两个表单水平/垂直中心与视口中心误差不超过 2px；旧内联表单因此 Red。配色断言默认与非默认头像、工作空间入口均为 `rgb(27, 43, 70)`，头像与入口描边为 `rgb(53, 80, 117)`，一级导航活动项同为 `rgb(27, 43, 70)`。实现后 `workspace.spec.ts` 8/8、`gateway-settings.spec.ts` 11/11 通过，`npm run typecheck` 与生产构建通过。
- 截图：`docs/screenshots/workspace-menu-popover.png`，1007×780 Chromium，浮层实测 380×268px、背景 `rgb(255, 255, 255)`、两个工作空间头像均使用统一深海军蓝；SHA-256 `91D573ED6EA3F6ADCD0356E4BEACCB6C66A2E3388BB916F1647AC6B6F388F55D`。
- 设置弹框截图：`docs/screenshots/workspace-settings-centered.png`，1007×780 Chromium，弹框 480×372px，中心误差小于 1px；SHA-256 `B8D3F01F688DEB7C2E54906FD516CFF82C082CA4CDEF2872778D5337AEC227F5`。
- 新建弹框截图：`docs/screenshots/workspace-create-centered.png`，1007×780 Chromium，弹框 480×372px，中心误差小于 1px；SHA-256 `5A97267DA7509F9824E75841A5BCCED00F10BD612712D33BFC65FEB91E60D17E`。
- 视觉结论：通过。入口位置、浮层尺寸与附图一致；设置和新建表单独立居中，不挤占切换浮层。
- 真实鉴权冒烟：not_evaluated。本轮不读取、输出或写入真实 Gateway Key；使用契约夹具验证请求路径、请求体、作用域头和错误处理，真实环境可用用户运行时配置复验。

## Chat Agent 选择补充（2026-11-16，实施前目标）

- 来源：`docs/hexa-client-demo.html` 的 `chatInspector()` / `agent-chips`；沿用工作台样式，在“会话”标签展示真实 Agent 选择卡片、名称与模型，当前选择具有明确选中态。
- 对话输入区只保留消息、附件、发送和生成取消操作；Agent、模型与 Gateway 配置统一放在右侧检查器，移动端通过上下文抽屉访问，不在输入区重复出现。
- 列表与 Agents 管理及二级导航共享真实 Gateway 数据；未配置、加载中、空列表、失败及重试均有明确提示，不用演示列表替代真实列表。
- 选择后模型与检查器同步，刷新恢复选择；已有消息或 response ID 时锁定 Agent，提供“更换 Agent 并新建对话”。新会话不沿用旧 response ID。
- 自动检查桌面选择、发送及 follow-up、刷新、跨模块选择、失败重试、空结果、移动端无横向溢出；截图检查亮色、深色、390px。

## 中间宽度布局修复（2026-11-16）

- 复现视口：857×611。二级导航在 900px 断点隐藏后，后置的三列网格仍为其保留 236px，导致对话主区被挤入第二列，右侧留下大块空白。
- 修复目标：900px 以下使用 `56px + minmax(0, 1fr)` 两列网格，对话主区从 x=56 开始占满剩余 801px，检查器贴齐视口右边缘。
- 自动验收：857px 中间视口断言 rail 宽 56px、main 宽 801px、会话检查器右边缘为 857px；390px 移动端继续使用抽屉检查器。

## 全高检查器与运行时选择（2026-11-16）

- Chat 右侧检查器在桌面端从视口 y=0 延伸到视口底部，默认宽度 320px，可拖动左边缘调整；主对话 header 与内容区为检查器预留横向空间。
- 检查器 header 的关闭按钮用于收起；收起后右侧保留窄型“上下文”入口用于重新展开。移动端仍使用抽屉，展开时不挤压主对话。
- “会话”标签提供 Agent 与模型两个原生选择列表。Agent 来自 `GET /v1/harnesses`，模型来自 `GET /v1/harnesses/{id}/models`。
- Agent 与模型随当前对话保存在浏览器本地状态；首次消息前可切换，开始会话后锁定，避免同一 `previous_response_id` 链路中途混用运行时。
- 对话输入区不再重复显示“上下文”、Agent、模型或 Gateway 配置，只保留附件、发送和生成取消操作。
- 模板节点对象迁移后补回画布坐标绑定，恢复节点拖动、端口连线、循环依赖拦截和保存后位置持久化。
- 验证截图：`docs/screenshots/chat-sidebar-full-height.png`，999×611；SHA-256 `1FD001A9555F6B7ABE12F94F55B7C5F246BFB9BBDD60A25C15C839F97018BD9E`。
- 输入区简化截图：`docs/screenshots/chat-composer-simplified.png`，1204×611；SHA-256 `37F332A98D73CFE1CFD6FE0F40BEE06B043F2FE4AAC9658A5BB7821FCEEF5AF9`。

- 设计来源：`docs/hexa-client-demo.html`，当前仓库工作区版本；目标是保留其应用框架、信息层级、状态表达和响应式行为。
- 目标页面：Chat、Tasks、Templates、Agents；桌面端以 Chromium/Chrome 和 Edge 为主，移动端以 390px 窄视口作为关键断点。
- 验收方法：Vite 热更新开发站点上的 Playwright 可访问性与交互测试、截图检查和生产构建检查。当前没有历史设计截图，因此结构和关键断点按设计稿中的明确 CSS 约束验收，细微像素差异作为后续 advisory。

## 本轮完成

- 外层应用改为带圆角、边框和阴影的工作台框架，桌面视口保留页面边距，窄视口切换为全屏布局。
- 一级 rail 使用设计稿的深色背景、蓝色活动指示条和紧凑图标按钮。
- 二级导航固定为 236px，并统一标题、列表、空状态和新建入口的间距与颜色。
- 主内容区域使用浅灰背景，消息、附件、输出文件、任务和 Agent 统一使用白色卡片和细边框。
- Chat 内容列收窄至约 820px，composer、模板标记和用户消息使用设计稿中的紧凑比例。
- 上下文面板改为右上浮层，窄视口下回落为内容流中的本地面板，避免遮挡输入区。
- Chat 右侧检查器已改为桌面默认展开的 320px 结构，包含“会话 / 产物 / 审批 / 工具”四个标签；移动端默认收起并以抽屉打开。
- 保留深色模式、移动端 rail、设置弹框和已有键盘焦点样式。

## 当前仍存在的差异

- 设计稿有完整的会话检查器、任务详情检查器和模板节点画布；当前实现已提供 Chat 上下文面板，但 Tasks/Templates 的右侧检查器仍是简化内容。
- 设计稿的 Chat 消息包含 Agent 头像、模型标签、状态 pill、工作流卡片和更丰富的产物视图；当前实现已显示 Agent、模型、附件和输出文件，消息结构仍需继续细化。
- 设计稿的 Tasks 页面是表格和详情页，当前实现使用任务卡片列表；Templates 页面当前是轻量节点编辑器，尚未达到设计稿的画布和属性面板密度。
- 设计稿使用统一的状态颜色、按钮尺寸和图标语义；当前部分状态仍依赖 Ant Design 默认 Tag/Button，需要逐步替换为客户端自己的状态组件。
- 浏览器实测受当前本地 Docker 容器生命周期影响：容器可被重启后退出，已通过重新启动并用 Playwright/浏览器检查恢复；该问题属于测试环境稳定性，不归因于客户端布局。

## 验收结论

- 功能：24 个客户端单元测试、类型检查、生产构建和 18 个 Playwright UI 用例全部通过；覆盖 Gateway 设置、Agent/模型选择、全高侧栏收起/展开、移动端抽屉及模板画布交互。
- 视觉：本轮的应用框架、rail、二级导航、主背景、卡片层级和 Chat 内容列已对齐到设计稿的主要结构。
- Advisory：Tasks、Templates 的完整设计稿形态、消息检查器细节和跨浏览器截图基线仍待后续阶段完成。
- 未评估：真实 Gateway CORS、真实 BYOK Provider、Chrome/Edge 实机差异和真实文件下载链路不在本轮 Docker 静态站点检查中。

## Gateway 真实接入验证（2026-11-13）

- Gateway 地址：本地 Console BFF 的 `/api/harness` 前缀；临时 API Key 创建成功，Bearer 鉴权和 `/v1/harnesses` 请求成功。
- 临时组织没有 Agent，无法从该组织发起响应；临时 Key 已在异常和正常路径中撤销。
- 现有本地组织读取到 5 个 Agent，但 `/v1/bases` 返回的 31 个基础能力中可用 Provider 数为 0，因此真实 Responses 对话被 Provider 配置阻塞。
- 该阻塞属于 Gateway 当前 Provider 配置外部依赖；本轮未修改 Gateway、Provider、认证或部署配置。
- 客户端自身的连接状态、鉴权失败、不可达、响应失败和 Provider 阻塞状态已有明确 UI/错误状态承载。

## Chat 检查器收缩展开控件（2026-11-16）

- 用户反馈：右侧“未配置 Gateway”选中元素所在页面需要新增收缩展开按钮；目标为检查器收起后仍有清晰、持久的右侧入口，同时展开后不保留重复浮层。
- 交互：桌面检查器 header 使用“关闭上下文”收起；收起后右上角出现 28×56 的贴边“展开上下文”控件，位置固定于视口右侧，点击后恢复 320px 检查器并隐藏该控件。移动端沿用默认收起和抽屉展开。
- 视觉：控件使用白色表面、细边框、左侧圆角、主色箭头和浅蓝 hover 态；与工作台既有控件尺寸一致，不遮挡消息输入区。
- 自动验收：先新增“chat inspector collapses and expands from a persistent right edge control”，确认初始浮层隐藏且贴边控件缺失导致 Red；实现后目标用例 Green，相关 `gateway-settings` 与 `chat-agents` Playwright 用例 13/13 通过，`npm run typecheck` 通过。
- 截图：收起态 `docs/screenshots/chat-inspector-toggle-collapsed.png`；展开态 `docs/screenshots/chat-inspector-toggle-expanded.png`；1280×611 Chromium，展示贴边控件和检查器恢复后的状态。

## 导航文字、图标与检查器标签（2026-11-16）

- 用户反馈：一级导航图标下默认显示文字；任务、模板、智能体图标建议更换；检查器标签从内容区上移到标题栏并使用 tab 形式。
- 交互：一级导航新增“对话 / 任务 / 模板 / 智能体”默认文字，设置弹窗提供“一级导航显示文字”开关，关闭后仅保留可访问名称和 title，并在刷新后保持。会话检查器标题移除，标签放入 56px header，使用 `role="tablist"`、`role="tab"` 和 `aria-selected`。
- 视觉：导航按钮改为图标加 11px 文字，默认选中仍使用深色活动底与左侧蓝条；任务改为 CarryOut，模板改为 FileText，智能体改为 Team 图标，二级行为同步使用“智能体”。检查器 tab 保持 30px 高度和浅色选中态，关闭按钮右侧对齐；设置弹窗中的开关使用单行 checkbox。
- 自动验收：先新增“inspector tabs move into the header and rail labels can be disabled in settings”，确认 header 内 tab 与导航文字开关缺失导致 Red；实现后目标用例 Green。相关 `gateway-settings`、`chat-agents` 和 `templates` Playwright 用例 23/23 通过；`gateway-settings` 单文件 10/10 复跑通过；`npm run typecheck` 通过。
- 截图：`docs/screenshots/rail-labels-inspector-tabs.png` 与 `docs/screenshots/rail-labels-setting.png`，1007×780 Chromium，展示导航文字、更换后的图标、检查器 header tab、当前“会话”选中态和设置开关。

## 一级导航上下排列（2026-11-16）

- 用户反馈：一级导航的图标和文字应为上下结构，而不是同一行。
- 交互与几何：导航按钮为 44×48，图标在上、10.5px 文字在下，间距 3px；图标和文字水平中心对齐。文字关闭后按钮仍保持同一可点击区域。
- 图标尺寸：导航图标独立设为 20px，不再继承 10.5px 的文字字号；文字使用独立 `.rail-label` 类，避免嵌套图标 `span` 被文字规则误伤。
- 自动验收：在现有目标用例中新增图标底边不高于文字顶边、两者水平中心差不超过 1px、图标宽高均不小于 20px 的断言；先确认横向布局和 10.5px 图标导致 Red，修复后 Green。相关 Playwright 用例 23/23 通过，`npm run typecheck` 通过。
- 截图：`docs/screenshots/rail-labels-stacked-large-icons.png`，1007×780 Chromium，展示四个一级导航入口的 20px 图标与文字上下排列。

## 一级导航视觉优化（2026-11-16）

- 间距与尺寸：桌面 rail 从 56px 调整为 60px，导航项改为 44×52、间距 8px；移动端 rail 从 48px 调整为 56px，保留默认文字而不压缩主内容。
- 层级：品牌 Logo 缩小为 30×30，工作区入口放大为 36×36，导航区上间距增至 16px；底部设置与主题入口统一为 40×40 点击区和 20px 图标。
- 选中态：移除左侧蓝色竖条，改为柔和蓝色底与 1px 内描边，避免深色底和竖条双重强调；未选中文字降低亮度，悬停使用低对比白色底。
- 可访问性：rail 内按钮新增 `focus-visible` 蓝色轮廓，键盘导航时状态清晰；文字和图标仍保持上下结构及中心对齐。
- 自动验收：相关 `gateway-settings`、`chat-agents`、`templates` Playwright 用例 23/23 通过，`npm run typecheck` 通过；新增 rail 宽度、导航按钮高度、8px 间距和底部图标尺寸断言，先确认旧样式 Red 后实现 Green。
- 截图：桌面 `docs/screenshots/rail-refined.png`，移动 `docs/screenshots/rail-refined-mobile.png`，Chromium 1007×780 与 390×844。

## 右侧检查器浏览器式标签栏（2026-11-16）

- 设计来源：用户附图的浏览器式右侧面板，顶部为浅色工具条、白底描边活动标签和右侧面板收起按钮。
- 结构：检查器 header 为“标签条 + 最右收起按钮”，移除新建和刷新控件。四个会话标签保持 `role="tab"`；活动标签显示功能图标、白底、细边框和轻阴影，非活动标签只显示文字。
- 折叠态：对话标题栏在 Gateway 状态右侧显示列表按钮和最右面板展开按钮。列表按钮只打开会话/产物/审批/工具菜单，不直接展开检查器；最右面板按钮负责展开。
- 操作：菜单选择某个标签后打开检查器并切换到对应标签；检查器内部收起按钮始终贴齐面板右侧。
- 响应式：标签条可横向滚动，固定收起按钮不被挤压；390px 抽屉中四个标签全部可见，移动端标签右边缘不超过收起按钮左边缘。
- 自动验收：覆盖活动标签边框、无新建/刷新控件、收起按钮贴右、折叠态列表和面板按钮顺序、列表菜单不直接展开、面板按钮展开以及移动端标签不重叠；先确认旧行为 Red，实现后 Green。相关 Playwright 用例 23/23 通过，`npm run typecheck` 通过。
- 截图：展开 `docs/screenshots/inspector-header-expanded.png`，折叠 `docs/screenshots/chat-header-collapsed-actions.png`，列表菜单 `docs/screenshots/chat-header-collapsed-menu.png`，Chromium 1033×780。

## 右侧检查器可调宽度与白色标签栏（2026-11-16）

- 用户反馈：右侧边栏需要支持左右拖拽调整宽度；顶部 tab 标签栏应与检查器内容区一致使用白色背景。
- 交互：检查器左边缘提供 10px 命中区的 `role="separator"` 拖拽手柄，桌面端左右拖动实时调整宽度；支持 `ArrowLeft` / `ArrowRight` 每次 16px 调整以及 `Home` / `End` 跳到最小 / 最大宽度。移动端抽屉保持固定宽度并隐藏手柄。
- 几何：默认宽度 320px，最小 280px、最大 560px，同时为主对话保留至少 420px；窗口缩放时自动收敛到可用范围，宽度写入 `localStorage` 的 `hexa.client.inspector-width`，刷新后恢复。
- 视觉：拖拽手柄命中区悬浮或键盘聚焦时显示 3×38px 主色提示条，拖动期间全局使用 `col-resize` 光标并禁止文本选择，不改变标签栏与内容区的层级；`.inspector-head` 由浅灰改为 `var(--hx-surface)`，亮色主题下为纯白 `rgb(255, 255, 255)`。
- 可访问性：手柄具有“调整上下文宽度”可访问名称、垂直方向、最小 / 最大 / 当前值，并支持键盘调整和可见焦点轮廓。
- 自动验收：先新增“chat inspector resizes from its left edge and keeps the header on a white surface”，确认缺少分隔手柄且 header 为 `rgb(241, 241, 244)` 导致 Red；实现后目标用例 Green。`gateway-settings.spec.ts` 11/11 通过，`npm run typecheck` 通过。
- 截图：`docs/screenshots/inspector-resizable.png`，1440×900 Chromium，检查器从 320px 拖至 445px，header 背景实测为纯白；SHA-256 `AE15F0EC62AE1D67D1B1B6973D4E82DB2C6A4E6F61BE509B01721FD8FA3CF377`。

## 智能体菜单机器人图标（2026-11-16）

- 用户反馈：一级导航“智能体”入口希望使用机器人样式的图标。
- 实现：主工作台与兼容客户端的“智能体”入口统一由 `TeamOutlined` 替换为 Ant Design `RobotOutlined`，沿用既有 20px 图标、上下文字结构、可访问名称和选中态。
- 自动验收：现有导航布局用例新增 `.anticon-robot` 数量断言，先确认旧图标导致 Red；替换后目标用例 Green，`npm run typecheck` 通过。
- 截图：`docs/screenshots/rail-robot-agent-icon.png`，1007×780 Chromium，机器人图标实测为 20×20px；SHA-256 `7FD16785957D03F55ADB63DE7AB75C9E4CF374A8B2475FB59B743A648D4FF4D3`。

## 统一深海军蓝 rail 配色（2026-11-16）

- 用户反馈：提供深海军蓝配色附图，希望工作空间与一级导航统一采用该视觉，不再混用橙色头像和亮蓝半透明选中态。
- 视觉令牌：卡片底色 `--hx-rail-card: #1b2b46`、描边 `--hx-rail-card-border: #355075`、悬停色 `--hx-rail-card-hover: #223a5c`；颜色集中定义在 `client/src/styles.css`，工作空间浮层和工作空间入口不再维护独立动态色。
- 应用范围：左侧工作空间入口、工作空间切换浮层中的全部头像、一级导航当前项统一使用深海军蓝卡片底；活动项以内描边表达选中层级，悬停仅在未选中态提亮。
- 自动验收：颜色断言覆盖工作空间入口、默认与非默认头像背景 `rgb(27, 43, 70)`、描边 `rgb(53, 80, 117)` 和一级导航活动项背景；相关 `workspace.spec.ts` 8/8、`gateway-settings.spec.ts` 11/11 通过，`npm run typecheck` 与生产构建通过。
- 截图：导航 `docs/screenshots/rail-unified-navy.png`，SHA-256 `168C9129D4BBCB74AD6C9AF5B15B16DD36FE286DAE58DE248A3A16427297A02E`；工作空间浮层 `docs/screenshots/workspace-menu-popover.png`，SHA-256 `91D573ED6EA3F6ADCD0356E4BEACCB6C66A2E3388BB916F1647AC6B6F388F55D`，均为 1007×780 Chromium。
- 视觉结论：通过。工作空间入口、空间头像和导航活动项形成统一的深蓝卡片层级，与深色 rail 保持足够对比；当前项仍可通过内描边和文字亮度识别。

## 回复详情原位展开（2026-11-19）

- 来源：用户“用时 2分钟 53秒 >”截图，明确要求正文上方原位展开，未知耗时只显示 ›，撤回误改的右侧配置折叠和纯图标标签。
- 结构：Agent 名称保留，下一行是灰色用时与箭头；无耗时记录时仅箭头，summary 可访问名称“回复详情”。详情默认收起，展开内容处于正常文档流，正文随之下移；无绝对定位、弹层、背景卡片或阴影。
- 内容：Harness、模型、状态、Gateway 公开思考摘要与工具名称/状态。每条回复独立保存，历史数据缺失时不伪造。复制操作保持图标和悬浮提示。
- 验证：Chromium 对话回归 5/5、Edge 目标用例 1/1；实测展开后正文向下移动超过 70px，详情 position 为 static；390px 无页面横向溢出；Enter 可展开，刷新恢复每条消息详情。真实 API/SQLite + HTTP Gateway 夹具 E2E 1/1，未发送额外真实模型请求。
- 截图：`docs/screenshots/chat-reply-details-desktop.png`（1440×900）SHA-256 `DDBE5E9D592B8C266747517C4D76BC6DDD1B9F2F2906E56F33593245FE87CB1C`；`docs/screenshots/chat-reply-details-mobile.png`（390×844）SHA-256 `732CB1FD7CBC1BE93686F12A60AA0C3151DF090ACC8484A1A052543AC4E9DF73`。Windows/Edge 截图检查通过。
- 当前工作树基线、命令与限制详见 `docs/changes/CHG-chat-reply-details/change-record.yaml`。

## 一级导航用户菜单（2026-11-16）

- 设计来源：用户要求在“一级导航栏最下方增加用户头像，点击弹框用于登录和退出及个人信息查看”；静态客户端以本机账户承载，后续应用后端复用同一入口和会话账户语义。
- 入口与几何：用户头像位于 rail 底部“设置、主题”之后，36×36 圆形深海军蓝卡片，白色首字或用户图标；头像垂直中心与 rail 对齐，点击后以 `rightBottom` 在头像右侧展开 286px 白色浮层。
- 未登录：App 浮层展示“未登录”和“登录”按钮；登录弹框使用 FastAPI 会话认证，不保存 Gateway 凭据。
- 已登录：头像显示显示名称首字；浮层展示“显示名称 / @用户名”、本机状态、静态版本说明，以及“个人信息”“退出登录”两个操作。个人信息弹框展示用户名、登录状态、当前工作空间、登录时间和资料存储位置。
- 交互：登录或退出后状态写入/移除 `localStorage['hexa.client.user']`，刷新后保持；退出登录同时回到未登录入口。浮层、登录弹框和个人信息弹框均可用键盘关闭。
- App-only：用户菜单复用统一头像和弹框；登录使用“登录 Hexa”会话弹框，退出调用 `POST /api/hexa/auth/logout`，个人信息标明“应用会话账户”。
- 自动验收：先新增“rail user menu logs in locally, shows profile details and logs out”，确认头像和弹框缺失导致 Red；实现后 `user-menu.spec.ts` 1/1 通过，覆盖底部顺序、圆形样式、登录持久化、无密码存储、个人信息、退出和 390px 无横向溢出。相关 `workspace.spec.ts` 8/8、`gateway-settings.spec.ts` 11/11、应用后端 `playwright.app.config.ts` 10/10 通过，`npm run typecheck` 与生产构建通过。
- 截图：未登录 `docs/screenshots/rail-user-menu-signed-out.png`，已登录 `docs/screenshots/rail-user-menu-signed-in.png`，个人信息 `docs/screenshots/rail-user-profile.png`，深色 `docs/screenshots/rail-user-menu-dark.png`，均为 1007×780 Chromium；SHA-256 分别为 `56561F7DB6392654601873DB8B40BFF1FBD8231C5BB8B404850D1E0B0E186A5D`、`36F62930BCEB00417322A9677764D6F141D6CCA94A44C48B1F23FE98B0C9411C`、`A1E7B30CBA7CEE0756E28126EFF0C2F63EE25CD1262F997F8561A5B06B6D9161`、`7D472E15735132B8840E023D2CA0CE5A72AC7C9B16A10F8DEA6FE26CE0FD2A0D`。
- 视觉结论：通过。入口位于 rail 最下方，圆形头像与深蓝 rail 层级一致；浮层、登录和个人信息弹框在亮色与深色主题下均保持清晰对比。
- 未评估：真实身份头像上传、密码修改和跨设备账户同步不在静态版本范围；应用后端只复用入口与既有会话登录/退出契约，不新增账户资料接口。
