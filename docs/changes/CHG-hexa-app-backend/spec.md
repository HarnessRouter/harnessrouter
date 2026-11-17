# 行为说明

- 已有需求、设计或契约引用：用户确认的“前端展示 + Python 后端”拆分方案；`AGENTS.md` 中 Hexa Cloud 删除契约。
- 实施方案：plan.md

## 目标行为

- 浏览器只访问独立 Hexa App API，不接触 Gateway API Key。
- FastAPI 后端使用 HttpOnly 服务端会话 Cookie 认证；登录成功后只向浏览器返回随机会话 Token，服务端保存其哈希。
- 后端使用服务端配置的 Gateway 地址和 API Key 调用现有 Gateway UHP 接口，向客户端提供工作空间、Agent/模型和会话能力的应用层入口。
- 未登录请求返回 401；无效凭据不泄露用户名、密码、Gateway Key 或完整上游错误。
- app 模式底部用户菜单使用真实用户名/密码登录；受保护 API 返回 401 时清除可见的已登录数据、停止旧请求更新并打开登录弹窗，保留草稿与最近会话索引以便重新登录恢复；不自动重发不确定消息。错误密码仅在登录表单提示；注销失败保留当前账户并允许重试。localhost 和 127.0.0.1 各自使用同源 Cookie。

## 边界与非目标

- 首期使用单用户管理员登录模型，数据表保留 `user_id` 以便未来扩展多用户。
- 数据库目标为 PostgreSQL；测试允许注入 SQLite 数据库以保持测试隔离。
- Gateway 继续作为执行面；本 Change 不修改 `gateway/`、Gateway API、CORS、Compose、Dockerfile、Runner 或 Cloud 功能。
- 首批实现包括健康检查、认证、会话、工作空间、Agent/模型读取和对话索引；Memory、Template、Workflow 后端化在后续 Change 实施。
- 不使用 JWT，不把 Gateway API Key 放到响应、Cookie、日志、URL、浏览器存储或构建产物。

## 验收

- `GET /healthz` 在服务启动后返回可探测状态。
- 使用正确管理员凭据登录返回 200 并设置 `HttpOnly` 会话 Cookie；Cookie 不包含服务端 Gateway Key。
- 错误登录返回 401；未登录访问受保护接口返回 401。
- 服务端会话存储随机 Token 的哈希，数据库中不保存原始 Token。
- `GET /api/hexa/agents` 通过服务端 Gateway Adapter 读取已有 `/v1/harnesses`；Gateway Key 只在服务端出站请求中使用。
- 对话消息接口使用稳定幂等键，并保存服务端 `previous_response_id`；上游不确定时不自动重复提交。
- 受保护接口的错误信息为用户可读摘要，不包含 API Key、完整请求体或敏感上游响应。
- app 模式的 Agent 页面支持创建、创建后重新读取列表、删除确认和失败后重试；服务端失败保留已加载列表，空列表明确显示为空，不使用演示数据。
- 新对话切换 Agent 时清空旧模型与旧选项，并等待该 Agent 的模型列表；迟到的旧请求不能覆盖新 Agent，模型读取失败时禁止发送并提供重试。已有会话保留其固定模型。
- 对话历史独立于 Agent 目录和当前消息恢复加载；会话切换不能使历史结果失效。列表提供加载、空、失败和重试状态，失败不清除已有列表或输入草稿；退出或认证失效后旧历史结果不能重新显示。
- app 检查器复用当前静态版的标题、标签、分区及信息行组件：桌面默认 320px 全高并可收起，移动默认关闭并以抽屉展开。Gateway 地址由应用后端管理，不提供浏览器 Key 输入；未绑定模板的会话显示“未使用模板”。产物、审批和工具只显示已有响应或明确空状态。
