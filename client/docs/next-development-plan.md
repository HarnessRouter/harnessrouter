# Hexa Client 后续开发计划

本计划继续严格限定在 `client/`、客户端文档、客户端测试和客户端构建配置。不得修改 `gateway/`、Gateway API、CORS、认证、数据模型、Compose、Dockerfile 或任何 Cloud 部署入口。

## 阶段一：视觉骨架收口

目标是让四个模块都遵循 `docs/hexa-client-demo.html` 的同一套页面骨架。

- 抽取客户端自己的 `AppFrame`、`Rail`、`Subnav`、`PageHeader`、`StatusPill` 和 `InspectorPanel` 组件。
- 把 Tasks 从卡片列表推进到设计稿中的表格、详情页、节点状态和右侧检查器。
- 把 Templates 从轻量表单推进到带节点画布、依赖连线、节点属性和保存状态的编辑器。
- 把 Agents 卡片补齐模型、后端、真实/演示状态、选择态和删除确认反馈。
- 统一深色模式下的颜色变量、边框、阴影、焦点环和空/加载/错误状态。

验收：四模块桌面视口结构检查、390px 移动视口检查、键盘 Tab 顺序检查；保存关键页面截图并记录视口。

## 阶段二：对话与文件体验

- 将右侧上下文浮层扩展为可折叠检查器，展示模板、Agent、模型、会话轮数、待发送附件、输入/输出文件和连接状态。
- 完善多附件队列：上传进度、失败重试、临时文件清理提示、图片缩略图、普通文件类型图标和键盘可操作移除。
- 完善消息卡片：文本增量、response 状态、文件注解、生成文件下载和安全预览。
- 会话切换时取消旧请求，刷新时恢复 draft、previous response ID、附件引用和输出文件。

验收：API/Responses 现有测试继续通过；新增附件、断流恢复、失败重试和安全预览的客户端测试；不把未确认的请求自动重复提交。

## 阶段三：Workflow、Agent、模板行为收口

- 远端 Workflow 继续以 Gateway 快照为唯一权威来源，补齐退避轮询、终态停止、节点 blocked 和旧快照保护。
- 创建远端 Agent 后重新读取列表确认，删除前确认，失败时保留原列表。
- 模板草稿编辑不递增版本，点击保存才递增版本；创建任务时固定模板 ID 和版本。
- 本地演示任务与远端任务用明确状态标签区分，禁止演示数据伪装为真实远端结果。

验收：补充 workflow、Agent、模板 UI 测试；覆盖空列表、网络失败、创建失败、删除失败、刷新恢复和重复点击。

## 阶段四：App 客户端与安全验收

- 保持 `npm run build` 输出 `client/dist`，构建物不包含 API Key。
- Gateway 地址和 API Key 只通过 FastAPI 服务端环境变量提供，客户端不保存连接凭据。
- 检查构建产物、URL、控制台和错误提示，确保不泄露 API Key、完整请求体或敏感响应。
- 维护同源 App API 反向代理和 HttpOnly Cookie 部署文档。

验收命令：

```powershell
npm test --prefix client
npm run typecheck --prefix client
npm run build --prefix client
npx playwright test --workers=1
```

## 阶段五：真实环境验收

- 使用当前已经配置的普通 BYOK Provider 完成首轮对话和 follow-up。
- 完成真实文件输入、生成文件或会话产物下载。
- 完成至少两个并行节点和一个依赖节点的 Workflow，并刷新页面恢复状态。
- 在 Chromium/Chrome、Edge 和移动视口检查 Chat、Tasks、Templates、Agents、焦点、错误提示和无重复消息。
- 如果 App API 反向代理或服务端配置阻塞浏览器请求，只记录为外部部署依赖，不修改 Gateway 解决。

## 完成标准

只有客户端测试、类型检查、构建、关键浏览器路径、真实连续对话、真实文件任务、真实多节点 Workflow、App API 部署文档和安全检查都具备证据时，才将 Hexa Client 标记为生产可用。Hexa Cloud 删除契约验证继续沿用仓库现有验证，不因客户端工作恢复任何 Cloud 入口。
