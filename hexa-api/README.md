# Hexa App API

这是 Hexa 的独立应用后端，负责浏览器会话、应用工作空间、会话索引、幂等消息入口以及 Gateway 的服务端代理。

## 认证边界

浏览器使用 `hexa_session` HttpOnly Cookie，不使用 JWT。Cookie 中只保存随机会话 Token；数据库只保存带服务端 session secret 的 HMAC-SHA-256 哈希。Gateway API Key 只通过 `HEXA_GATEWAY_API_KEY` 注入后端进程，不能配置到 client、localStorage、URL 或错误提示中。

首期为单用户管理员模型，使用 `HEXA_ADMIN_USERNAME` 和 PBKDF2-SHA256 格式的 `HEXA_ADMIN_PASSWORD_HASH`。生成密码哈希：

```powershell
python -c "import sys; sys.path.insert(0, 'hexa-api'); from app.auth.passwords import hash_password; print(hash_password(sys.argv[1]))" "your-password"
```

## 本地运行

先准备 PostgreSQL，并设置 `hexa-api/.env.example` 中的变量。开发验证可以将 `HEXA_DATABASE_URL` 指向 SQLite，但生产使用 PostgreSQL。

```powershell
$env:HEXA_DATABASE_URL = 'postgresql+psycopg://hexa:hexa@127.0.0.1:5432/hexa'
$env:HEXA_GATEWAY_URL = 'http://127.0.0.1:3000/api/harness'
$env:HEXA_COOKIE_SECURE = 'false'
python -m uvicorn app.main:app --app-dir hexa-api --host 127.0.0.1 --port 4010 --reload
```

生产数据库必须按以下顺序执行全部迁移，再启动新版 API：

1. `migrations/001_initial.sql`
2. `migrations/002_tasks.sql`
3. `migrations/003_agent_templates.sql`
4. `migrations/004_task_template_source.sql`
5. `migrations/005_task_artifacts.sql`
6. `migrations/006_conversation_execution.sql`
7. `migrations/007_node_execution.sql`
8. `migrations/008_node_orchestration.sql`
9. `migrations/009_node_iterations.sql`

应用启动不会自动创建 PostgreSQL 表，也不会连接未配置的默认数据库。SQLite 只用于测试工厂；SQLite 开发数据库启动时会补齐 Agent 模板表、任务来源模板字段、任务版本身份字段和任务 Artifact 表，已有任务按已有版本号回填可确定的版本 ID。Agent 模板独立于任务工作流模板，保存名称、说明、运行时、默认模型和系统提示词，不保存 Gateway 凭据。`004_task_template_source.sql` 给现有任务增加可空的来源模板及固定版本字段，旧任务不会推测补写来源。`005_task_artifacts.sql` 只保存 Gateway 文件引用和任务权限元数据，不复制文件内容。

任务工作台通过 Cookie API 读取当前工作区任务、模板与运行历史，创建任务、保存工作流、启动/控制运行、提交人工选择和读取节点调试；活动运行通过 SSE 更新，断线后只读轮询恢复。Task 返回当前 `WorkflowRevision` 的 ID、版本号和 `saved` 状态；模板任务同时返回固定的 TemplateVersion 来源。Run 通过 `workflow_revision_id` 固定已保存版本，并在 `execution_snapshot` 中保存工作流、输入、Agent 配置和来源版本，不能引用本地草稿。任务、Run、节点、调试尝试、模板和 Artifact 列表返回分页元数据，客户端按页加载。`save-as-template` 可携带 `workflow_revision` 选择已保存版本；默认新建模板，显式传 `template_id` 时才向该用户同工作区模板追加版本。运行图使用 Run 的工作流快照，拖动和重放不写业务数据。任务 Artifact 只保存 Gateway 文件引用，下载由 hexa-api 校验权限后代理，不把 Gateway 文件 ID 或凭据暴露给 client。

## API 首期范围

- `GET /healthz`
- `POST/GET /api/hexa/auth/login|session`、`POST /api/hexa/auth/logout`
- `GET/POST /api/hexa/workspaces`、`POST /api/hexa/workspaces/select`
- `GET/POST /api/hexa/agents`、`DELETE /api/hexa/agents/{agent_id}`、`GET /api/hexa/agents/{agent_id}/models`
- `GET/POST /api/hexa/conversations`
- `GET /api/hexa/conversations/{id}`、`GET /status`
- `POST /api/hexa/conversations/{id}/messages`
- `POST/GET /api/hexa/tasks`、`GET /api/hexa/tasks/{id}`、`PUT /api/hexa/tasks/{id}/workflow`
- `POST/GET /api/hexa/tasks/{id}/runs`、`GET /api/hexa/runs/{id}`、`GET /api/hexa/runs/{id}/events`
- `GET /api/hexa/runs/{id}/nodes`、`GET /api/hexa/tasks/{id}/artifacts`、`GET /api/hexa/runs/{id}/artifacts`、`GET /api/hexa/node-runs/{id}/artifacts`
- `GET /api/hexa/artifacts/{id}`、`GET /api/hexa/artifacts/{id}/content`
- `POST /api/hexa/runs/{id}/continue|pause|cancel` and node retry/skip controls
- `GET /api/hexa/node-runs/{attempt_id}`, template version routes, and save-as-template

消息接口使用 `Idempotency-Key`。Gateway 响应流中断时，后端保留不确定状态并返回 409 给重复提交，客户端应先读取会话状态，不自动重新创建远程任务。

回复消息可包含 `execution`：独立记录 Harness、模型、状态、耗时（毫秒）、Gateway 公开思考摘要和工具名称/状态。流式快照同步当前详情，刷新后按消息恢复；旧消息无记录时省略。只保存工具名称和状态，不包含工具原始参数。SQLite 启动时兼容新增列；PostgreSQL 部署须通过 `python migrate.py` 按顺序应用 `006_conversation_execution.sql` 和 `007_node_execution.sql`。

## 前端热更新联调

后端按上面的 `--reload` 命令启动，另开终端运行前端：

```powershell
$env:HEXA_API_PROXY = 'http://127.0.0.1:4010'
npm run dev --prefix client
```

访问 `http://127.0.0.1:4173`，使用配置的管理员用户名及密码登录。Vite 同源代理保留浏览器 Origin，Cookie 随 `/api/hexa` 请求发送；生产也应由同一 origin 的反向代理转发 App API。当前 client 只有 App 模式，修改 FastAPI 代理地址后重启 Vite。浏览器不需要 Gateway 地址或 Key。未配置有效后端环境时登录不可用，不使用测试夹具替代真实服务。

Agent 页面通过 App API 创建、确认删除并重读服务端列表；失败时保留原列表和表单。新对话选择 Agent 后加载对应模型，模型加载失败提供重试并禁止发送；已有对话固定 Agent 和模型。

Agent 页面中的“模板库”通过 `GET /api/hexa/agent-templates/gateway` 从现有 Gateway `/v1/bases` 读取基础模板；`GET/POST /api/hexa/agent-templates` 和 `PUT/DELETE /api/hexa/agent-templates/{id}` 管理当前用户的自定义模板。两种来源独立读取，上游失败可重试且不阻塞客户模板；使用模板先打开可编辑的创建表单。卡片/列表视图偏好保存在浏览器，模板内容持久化在应用数据库。

## 范围边界

后端只调用现有 Gateway UHP 接口，不改变 Gateway、CORS、Compose、Dockerfile、Runner 或任何 Hexa Cloud 删除契约。任务、工作流和运行历史由 Hexa App API 管理，client 通过 App API 展示和操作。


集合展开记录通过 `input.item_node_run_ids` 固定当前项尝试。活动 Run 的失败集合可向
`POST /api/hexa/runs/{run_id}/nodes/{node_id}/retry` 发送 `{}`（全部失败/取消项）或
`{"item_node_run_id": 123}`（当前清单指定失败项），并携带新的 `Idempotency-Key`。
成功项不会重复执行；新项追加 attempt，聚合保序引用当前清单。终态 Run 仍需创建新的 Run。
`attempt` 表示控制/项执行尝试，聚合项数使用 `input.item_count`，循环轮次使用 `iteration`。


终态集合项恢复在创建 Run 时发送：
```json
{"kind":"rerun","target_node":"worker","resume_from_run_id":71,"item_node_run_id":123}
```
省略 `item_node_run_id` 时显式恢复全部失败/取消项。来源必须属于同 Task，且工作流版本、任务输入和所用 Agent 公开配置一致。
接口创建新的 Run 并保存 `execution_snapshot.resume`，成功项/上游通过本 Run 的 `reused_from` 记录引用来源结果，旧 Run 不变。
循环内恢复保留 iteration；人工确认须在新 Run 重新提交。独立失败分支不自动重放；新 Run 仍可能因这些分支失败。
