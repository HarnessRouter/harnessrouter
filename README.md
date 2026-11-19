# Hexa2

Hexa2 是一个面向自托管环境的 Agent 工作流应用。它把 Agent、模型、工具、文件、任务流程和运行记录放在同一套本地应用中，帮助用户创建任务、编排多个 Agent、启动运行、处理人工选择并查看结果。

Hexa2 不依赖云端控制面。普通 BYOK 模型服务商（包括 Azure OpenAI 和 AWS 兼容服务）、第三方 Agent 运行时、浏览器运行时、UHP 连接和 Runner 管理继续由自托管 Gateway 提供；应用层通过服务端代理调用 Gateway，浏览器不直接持有 Gateway 凭据。

## 当前架构

```text
浏览器
  │  同源 /api/hexa，HttpOnly hexa_session Cookie
  ▼
Hexa App API（hexa-api，FastAPI）
  │  任务、工作流、模板、运行记录和权限的权威来源
  ▼
Gateway（UHP / OpenAI Responses-compatible API）
  │
  ▼
Runner 与第三方 Agent 运行时
```

- `client/`：Hexa2 前端，负责任务列表、工作流画布、运行状态、模板和结果展示。
- `hexa-api/`：应用后端，负责认证、工作区、Agent、任务、模板、WorkflowRevision、Run、NodeRun 和 Artifact 的持久化与状态转换。
- `gateway/`：自托管 Agent 执行网关，负责 UHP 接口、会话、文件、工具、浏览器、UHP 连接和 Runner 协作。
- `runner/`：在隔离工作区中运行 Agent harness 和第三方运行时。
- `protocol/`：Unified Harness Protocol（UHP）的协议定义、OpenAPI/JSON Schema 和一致性测试。

任务和运行记录以 `hexa-api` 保存的数据为准。Gateway 只负责执行 Agent 请求，不作为 Hexa 任务历史的权威来源。

## 本地开发

### 1. 配置应用后端

先准备 PostgreSQL，并参考 [hexa-api/.env.example](hexa-api/.env.example) 设置应用后端变量。开发验证可以使用 SQLite；生产环境使用 PostgreSQL。

至少需要配置：

- `HEXA_DATABASE_URL`：应用数据库连接。
- `HEXA_GATEWAY_URL`：自托管 Gateway 的 UHP 地址，例如 `http://127.0.0.1:3000/api/harness`。
- `HEXA_GATEWAY_API_KEY`：仅注入 `hexa-api` 进程，不写入前端、URL、localStorage 或错误提示。
- `HEXA_ADMIN_USERNAME` 和 `HEXA_ADMIN_PASSWORD_HASH`：应用管理员账户。

生成管理员密码哈希：

```powershell
python -c "import sys; sys.path.insert(0, 'hexa-api'); from app.auth.passwords import hash_password; print(hash_password(sys.argv[1]))" "your-password"
```

生产数据库启动前，按顺序执行 `hexa-api/README.md` 中列出的迁移文件。应用不会自动为 PostgreSQL 创建表。

### 2. 启动 Hexa App API

```powershell
python -m uvicorn app.main:app --app-dir hexa-api --host 127.0.0.1 --port 4010 --reload
```

### 3. 启动客户端

另开终端：

```powershell
$env:HEXA_API_PROXY = "http://127.0.0.1:4010"
npm run dev --prefix client
```

访问 [http://127.0.0.1:4173](http://127.0.0.1:4173)，使用应用管理员账户登录。浏览器只访问同源 `/api/hexa`，不需要 Gateway 地址、Gateway API Key、组织成员或模型凭据。

更完整的应用后端说明见 [hexa-api/README.md](hexa-api/README.md)，前端说明见 [client/README.md](client/README.md)。

## 任务、工作流和运行记录

Hexa2 用以下对象保存一项工作的完整过程：

```text
Template → TemplateVersion
                └── 显式使用模板创建 Task
Task → WorkflowRevision
          ├── Run A → NodeRun / Artifact
          └── Run B → NodeRun / Artifact
```

- `Task` 是用户看到的任务身份和当前结果指针。
- `WorkflowRevision` 是不可变的节点图、依赖、输入声明和执行配置。
- `Run` 是一次执行，固定绑定启动时的 WorkflowRevision 和执行配置快照。
- `NodeRun` 是 Run 中一个节点的一次执行尝试，追加保存输入、输出、日志和错误。
- `TemplateVersion` 只保存可复用的工作流定义，不保存运行记录、结果、产物或密钥。

编辑任务草稿不会改变已有运行。点击“保存任务流程”才会生成新的 WorkflowRevision；点击“运行”才会创建新的 Run；“保存为模板”和“重放”是独立操作。重放运行记录只回看历史事件，不重新执行 Agent。详细的版本关系和保存边界见 [任务模块设计规范](docs/changes/CHG-task-centric-workflow/spec.md#版本关系与保存边界)。

## 能力范围

- Agent 和模型配置，以及可复用的 Agent 模板。
- 任务创建、工作流画布编辑、依赖和输入映射。
- 并行和串行 Agent 节点、人工门控、重试、跳过、暂停、取消和终态重跑。
- 运行历史、节点调试、结构化错误、SSE 状态更新和断线恢复。
- 文件、Artifact、会话、浏览器运行时、第三方 Agent 运行时、UHP 连接和 Runner 管理。
- BYOK 模型服务商，包括 Azure OpenAI、AWS 兼容服务和其他 OpenAI-compatible 服务。

Hexa2 不提供云端部署、上传、目标工作区、云端账号余额、云端密钥握手或 hosted provider 入口。相关边界见 [云端能力删除契约](docs/changes/CHG-hexa-remove-cloud-contract/spec.md)。

## 安全边界

- 浏览器只持有 `hexa_session` HttpOnly Cookie。
- Gateway 地址和 Gateway API Key 只配置在 `hexa-api` 服务端进程。
- 应用后端不把授权头、API Key 或敏感请求头写入任务、运行记录或客户端响应。
- 每次 Run 保存执行配置快照，但不保存密钥、授权头或 API Key。
- 调试输入、输出和错误在写入数据库前脱敏，读取时再次按字段过滤。
- 任务、模板、运行记录和 Artifact 按应用用户与工作区检查权限。

## 验证

```powershell
npm run typecheck --prefix client
npm test --prefix client
npm run build --prefix client
python -m pytest hexa-api/tests gateway/tests
```

根据改动范围选择相关测试；完整命令、接口范围和迁移说明分别见 [client/README.md](client/README.md) 与 [hexa-api/README.md](hexa-api/README.md)。

## UHP

[Unified Harness Protocol（UHP）](https://unifiedharnessprotocol.org) 是 Hexa Gateway 对外提供的版本化 Agent 执行协议。它定义了 harness 选择、持久会话、文件、取消、流式进度以及工具和技能的执行语义，并兼容 OpenAI Responses API 的任务接口。

本仓库包含协议文档、机器可读 Schema 和一致性测试：

- [协议说明](protocol/README.md)
- [OpenAPI 和 JSON Schema](protocol/schema)
- [一致性测试](protocol/conformance)
- [协议治理](protocol/GOVERNANCE.md)
