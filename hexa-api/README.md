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

生产数据库初始化按顺序执行 `migrations/001_initial.sql` 和 `migrations/002_tasks.sql`；部署流程必须先执行这些 SQL。应用启动不会自动创建 PostgreSQL 表，也不会连接未配置的默认数据库。SQLite 只用于测试工厂。

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
- `POST /api/hexa/runs/{id}/continue|pause|cancel` and node retry/skip controls
- `GET /api/hexa/node-runs/{attempt_id}`, template version routes, and save-as-template

消息接口使用 `Idempotency-Key`。Gateway 响应流中断时，后端保留不确定状态并返回 409 给重复提交，客户端应先读取会话状态，不自动重新创建远程任务。

## 前端热更新联调

后端按上面的 `--reload` 命令启动，另开终端运行前端：

```powershell
$env:HEXA_API_PROXY = 'http://127.0.0.1:4010'
npm run dev --prefix client
```

访问 `http://127.0.0.1:4173`，使用配置的管理员用户名及密码登录。Vite 同源代理保留浏览器 Origin，Cookie 随 `/api/hexa` 请求发送；生产也应由同一 origin 的反向代理转发 App API。当前 client 只有 App 模式，修改 FastAPI 代理地址后重启 Vite。浏览器不需要 Gateway 地址或 Key。未配置有效后端环境时登录不可用，不使用测试夹具替代真实服务。

Agent 页面通过 App API 创建、确认删除并重读服务端列表；失败时保留原列表和表单。新对话选择 Agent 后加载对应模型，模型加载失败提供重试并禁止发送；已有对话固定 Agent 和模型。

## 范围边界

后端只调用现有 Gateway UHP 接口，不改变 Gateway、CORS、Compose、Dockerfile、Runner 或任何 Hexa Cloud 删除契约。任务、工作流和运行历史由 Hexa App API 管理，client 通过 App API 展示和操作。
