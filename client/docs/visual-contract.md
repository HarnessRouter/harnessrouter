# Hexa Client UI 视觉契约与审查记录

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
