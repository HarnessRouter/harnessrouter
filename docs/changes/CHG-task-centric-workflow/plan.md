# 实施方案

- 行为、边界与验收依据：`spec.md`。
- 视觉验收：`visual-contract.md`。
- 平台验收：`platform-matrix.md`。
- 执行记录：`change-record.yaml`。

## 方案与依赖

- 任务后端新增在 `hexa-api/app/tasks/`，复用现有认证、SQLAlchemy session factory、`AppWorkspace` 权限边界和 `GatewayClient`。
- `hexa-api` 负责状态机和调度；`client` 通过 app API 读写，不在 `main.tsx` 保存权威运行状态，不直接调用 Gateway 执行任务。
- 数据库使用新增迁移文件 `hexa-api/migrations/002_tasks.sql`；SQLite 测试工厂继续使用 SQLAlchemy metadata，生产 PostgreSQL 按部署流程执行迁移。
- 先实现领域状态与 API 契约测试，再实现持久化和执行器，最后接入 client 页面。每个行为按 Red → Green → Refactor 推进。
- 运行调度采用 `hexa-api` 进程内异步任务，首版按单实例部署；进程恢复时将无法确认的活动节点标记失败，不自动重放外部 Agent 请求。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 建立 `Task`、`WorkflowRevision`、`TemplateVersion`、`Run`、`NodeRun`、结果指针和人工决定的领域类型；实现状态转换、DAG/规模校验、输入引用校验、Task 状态推导和 `stale` 派生 | 先新增并运行领域单元测试 Red；覆盖 AC-2、AC-4、AC-6、AC-7、AC-9、AC-13 |
| 2 | 增加 SQLAlchemy 模型、`002_tasks.sql`、任务服务和认证/工作区权限检查；实现版本冲突、单活动 Run、幂等请求、写入前脱敏和分页查询 | hexa-api 持久化集成测试；覆盖 AC-1、AC-7、AC-12、AC-13 |
| 3 | 实现 `hexa-api` 任务、工作流、Run、NodeRun、模板 REST 接口和 SSE 事件流 | FastAPI TestClient/API 集成测试，覆盖错误码、权限、冲突、分页和响应字段；覆盖 AC-1、AC-2、AC-6、AC-10、AC-11 |
| 4 | 接入进程内执行器和 `GatewayClient`；实现并行调度、人工门控、继续、阶段续编、重试、跳过、取消、终态重跑、采用结果和恢复 | 使用 fake GatewayClient 的服务集成测试，再运行真实本地 Gateway 冒烟；覆盖 AC-3、AC-4、AC-5、AC-6、AC-8、AC-9、AC-13 |
| 5 | client 增加任务 API 客户端、任务列表、`/tasks/:id` 路由、共享 TaskCanvas、节点检查器、运行时间线和调试视图；client 只展示 API/SSE 状态 | client 单元/API 测试、Playwright 桌面和移动 E2E；覆盖 AC-1、AC-2、AC-10、AC-14 |
| 6 | 接入模板创建、保存为模板、空白任务创建、错误/加载/恢复状态和静态站点详情路由回退 | 模板集成测试、完整流程 E2E、`vite preview` 直接访问与刷新测试；覆盖 AC-1、AC-11、AC-14 |
| 7 | 执行安全、数据库迁移、删除任务、共享 Artifact 引用检查、PostgreSQL 建表冒烟和交付复核 | 运行 hexa-api 相关回归、client 相关回归、平台矩阵和安全数据流检查；更新 `change-record.yaml`，未验证项不得标记通过 |

## 恢复与收尾

- 新接口采用新增路径，旧 Gateway 接口不修改。任务功能异常时，client 保留任务列表和错误重试入口；服务端保留已写入的 Run 历史。
- 进程重启恢复采用“标记不确定失败、不自动重放”的安全策略；用户可以通过终态重跑显式开始新的 Agent 请求。
- 文档完成后，`spec.md` 作为任务领域长期契约；`plan.md` 和 `change-record.yaml` 保留实施证据，接口稳定后同步到 `hexa-api/README.md`。
