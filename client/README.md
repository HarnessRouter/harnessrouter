# Hexa Client

Hexa Client 现在只有 FastAPI App 模式。浏览器通过同源 `/api/hexa` 访问 Hexa 应用服务，由应用服务端调用现有 Gateway；浏览器不保存、不接收 Gateway API Key。客户端不包含 Cloud 部署、Cloud 账号或 hosted provider 能力。

## 本地热更新

先运行开发启动脚本配置应用服务端凭据和 Gateway 环境变量，再启动 FastAPI：

```powershell
..\scripts\start-hexa-dev.ps1
```

首次运行会安全地询问管理员密码和 Gateway API Key，并将配置保存到项目根目录的 `.env.hexa-dev`（已加入 Git 忽略）；后续启动会自动复用配置和 `hexa-api/hexa-dev.db`。

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

## 端到端测试

`playwright.e2e.config.ts` 启动真实 Vite + FastAPI App API + 一次性 HTTP Gateway 夹具，覆盖登录/会话恢复、工作区隔离、对话与 SSE、Agent 详情与模板、任务工作流、人工门控、运行快照、模板版本、Artifact 下载、SSE 断线恢复、节点重跑、归档和移动端布局。

```powershell
cd client
npm run test:e2e -- --workers=1
# 仅跑 Edge 跨浏览器用例
npx playwright test -c playwright.e2e.config.ts --project=edge
```

夹具使用 `hexa-api/tests/serve_e2e.py`，SQLite 数据库位于系统临时目录，端口默认为 `4020`（Vite）、`4021`（Gateway 夹具）、`4022`（App API）。测试只会写入一次性数据库，不会连接开发或生产 Gateway；真实模型与 PostgreSQL 不在该套件范围内。

构建输出为 `client/dist`。生产环境应让静态文件和 `/api/hexa` 由同一 origin 提供，或由反向代理将 `/api/hexa` 转发到 FastAPI。构建产物不写入 Gateway API Key。

## 当前能力

- HttpOnly Cookie 登录、注销和会话过期恢复；
- 对话历史、连续对话、幂等发送和刷新恢复；
- FastAPI 管理的 Agent 列表、模型选择、创建和删除；
- Agent 模板库：从 Gateway 拉取基础模板，客户自定义模板的新建、编辑、删除和使用，以及列表/卡片切换、搜索与来源筛选；
- 文件上传、会话文件、输出文件安全预览和下载；
- 全高会话上下文栏、桌面 44px 收起把手、移动端抽屉、连接状态和恢复状态；
- 我的任务、运行记录和模板管理使用单一 table + 全高可收缩详情栏；1440px 下运行/模板详情宽 720px、任务详情宽 424px，窄桌面按容器宽度收缩并保留可扫描的列表宽度；
- 客户端本地模板编辑和任务快照展示。

Memory、Template 持久化、Workflow 执行的应用后端接口仍按后续变更计划推进。

## 安全边界

- Gateway 地址和 API Key 只配置在 FastAPI 进程环境；
- 浏览器只持有 `hexa_session` HttpOnly Cookie；
- API 错误不会显示 API Key、完整请求体或敏感上游响应；
- 生产不通过 Vite `/v1` 代理访问 Gateway；
- 不修改 Gateway、CORS、Compose、Dockerfile 或 Cloud 删除契约。
