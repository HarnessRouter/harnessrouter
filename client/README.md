# Hexa Client

Hexa Client 现在只有 FastAPI App 模式。浏览器通过同源 `/api/hexa` 访问 Hexa 应用服务，由应用服务端调用现有 Gateway；浏览器不保存、不接收 Gateway API Key。客户端不包含 Cloud 部署、Cloud 账号或 hosted provider 能力。

## 本地热更新

先按 [Hexa App API](../hexa-api/README.md) 配置应用服务端凭据和 Gateway 环境变量，再启动 FastAPI：

```powershell
python -m uvicorn app.main:app --app-dir hexa-api --host 127.0.0.1 --port 4010 --reload
```

另开终端启动唯一的客户端入口：

```powershell
cd client
$env:HEXA_API_PROXY = "http://127.0.0.1:4010"
npm run dev
```

访问 `http://127.0.0.1:4173`，使用 FastAPI 管理员账户登录。Vite 只代理 `/api/hexa`；浏览器不需要 Gateway 地址、API Key、组织、成员、模型或 backend 配置。

## 构建和部署

```powershell
npm run typecheck --prefix client
npm test --prefix client
npm run build --prefix client
```

构建输出为 `client/dist`。生产环境应让静态文件和 `/api/hexa` 由同一 origin 提供，或由反向代理将 `/api/hexa` 转发到 FastAPI。构建产物不写入 Gateway API Key。

## 当前能力

- HttpOnly Cookie 登录、注销和会话过期恢复；
- 对话历史、连续对话、幂等发送和刷新恢复；
- FastAPI 管理的 Agent 列表、模型选择、创建和删除；
- 文件上传、会话文件、输出文件安全预览和下载；
- 右侧会话检查器、移动端抽屉、连接状态和恢复状态；
- 客户端本地模板编辑和任务快照展示。

Memory、Template 持久化、Workflow 执行的应用后端接口仍按后续变更计划推进。

## 安全边界

- Gateway 地址和 API Key 只配置在 FastAPI 进程环境；
- 浏览器只持有 `hexa_session` HttpOnly Cookie；
- API 错误不会显示 API Key、完整请求体或敏感上游响应；
- 生产不通过 Vite `/v1` 代理访问 Gateway；
- 不修改 Gateway、CORS、Compose、Dockerfile 或 Cloud 删除契约。
