# UI 视觉契约

- 来源：当前 client 桌面/移动布局、用户要求的全高右检查器及 composer 简化；当前唯一入口为 App 模式。
- 页面：app 模式 Chat，1440×900、390×844，Chromium。登录使用 Ant Design Modal，键盘可提交、错误可读；不显示 Gateway Key 输入。
- 结构：导航、会话列表、主消息栏、可折叠 320px 右检查器；移动默认关闭，操作后打开抽屉。模型/Agent 置于右侧，composer 仅消息、附件和发送。
- 状态：登录加载/失败、Agent 空/失败、会话恢复/失败、请求 unknown 明确显示；不以演示结果替代远程结果。
- 验收：app-ui/chat.spec.ts 验证登录到刷新恢复全流程、无直接 Gateway 请求、移动无横向溢出；人工截图检查可读性/对齐，未覆盖浏览器明确记未评估。
- 证据及 Red/Green：统一记录 change-record.yaml；当前 stub 页面用于确认 UI 行为缺失的有效 Red。
- Agent 页面沿用现有导航与卡片，顶部放置“刷新列表”和“创建 Agent”。创建弹窗提供名称、后端、默认模型、系统提示词；错误保留表单。删除使用二次确认弹窗，失败保留卡片。异步操作有加载文字，错误可重试，控件具备可访问名称；1440×900 和 390×844 无横向溢出。
- 导航回归修复（2026-11-16）：App 模式保留对话、任务、模板、智能体四项及原有图标顺序、44×52 按钮、10.5px `.rail-label`、深海军蓝当前项。沿用 `hexa.client.rail-labels` 偏好并可在应用设置中修改；设置不再打开 Gateway 配置。任务展示已有客户端快照，未迁移的远端执行入口禁用并说明原因；模板复用客户端编辑器和本地版本保存。切换模块返回对话时保留消息与草稿。1440×900/390×844 检查菜单、选中态、文字开关及溢出。
- 用户指定的动态 UI 真源：本机 4174 的历史源码已用于对齐；当前 App 唯一入口使用 `NavigationRail`、`UserMenu`、`AppTasks`、`Templates`、`ChatInspector` 和同一份 styles.css。用户菜单连接真实 HttpOnly 登录/退出；不再保留静态版本或 direct 模式入口。
- 2026-11-17 右侧检查器：当前参考源码为 56px 顶栏、10px 圆角选中标签和图标、边框信息行；替代早期蓝色下划线设想。两种入口共用 `ChatInspector.tsx` 与 `.inspector-head/.inspector-tabs/.inspector-section/.inspector-kv`，内容顺序为参与 Agent、连接、上下文，正文独立滚动。app 模式地址显示后端托管，模板显示真实未绑定状态。桌面 1440×900 检查 x 右贴边、y=0、宽 320、高 900；移动 390×844 默认收起、展开贴右且全高、遮罩关闭、无横向溢出。深色沿用共享 tokens；折叠后 composer 可用宽度增加。
- 自动化验收：`tests/app-ui/navigation.spec.ts` 覆盖上述尺寸和交互，Chromium/Edge 截图位于系统临时目录 `hexa-app-inspector-{desktop,dark,mobile}.png`；已核对桌面及移动渲染。浏览器控制连接超时，未使用该控制服务做真实 BYOK 人工验收；Playwright 使用真实浏览器渲染，API 受控夹具不代表生产 Provider 验收。工作空间弹窗继续留待后续统一。
