# 行为说明

- 需求来源：2026-11-19 用户确认保留 PG 改造并按后续计划推进。
- 已有契约：../CHG-hexa-app-backend/spec.md、../CHG-task-centric-workflow/spec.md#版本关系与保存边界。
- 实施方案：plan.md。

## 目标行为

在独立的一次性 PostgreSQL 16 数据库上，运行仓库真实迁移和应用 API，验证全新建库、已有任务版本升级、重复迁移、任务保存与冲突、历史快照、Artifact、删除和重启恢复。SQLite 继续用于本地开发和快速测试。现有 PG 迁移和执行进度改造保留。

现有 SQLite/HTTP 夹具证据不代替本次真实 PostgreSQL 或 Linux Compose 证据；生产数据库不在本次操作范围内。

## 边界与非目标

- 使用独立 Compose 项目、数据库和持久卷，不连接或改动当前 Gateway、Runner 或 memories 数据库。
- 复用迁移入口、应用工厂、Cookie 权限、任务领域测试和受控 Gateway；只修复验收中发现的兼容问题。
- 执行进度与其他并行工作保留，不整体暂存或回退。迁移包含当前工作树的 007，证据须注明工作树基线。
- 不实现多实例调度、团队协作画布、生产数据迁移、真实模型调用或自动合并 MR。
- 本次不改变 UI，UI 过程展示的视觉验收仍属于 CHG-execution-progress。

## 验收

- 真实 PostgreSQL 上通过 CLI 按顺序运行 001–007，重复运行不破坏数据；--check 不写业务数据。
- 旧库保存 Task、WorkflowRevision、Run、NodeRun 后升级，版本身份正确回填，内容和运行快照不变，过程列有兼容默认值。
- 同一 API 领域测试可以显式选择独立 PG schema；未配置时继续使用隔离 SQLite。PG 选择后的连接或迁移失败必须失败，不能回退 SQLite。
- 任务、模板版本、冲突、历史 Run、Artifact 权限与清理、删除及执行进度在真实 PG 上符合既有任务契约。
- Compose 从迁移启动到 healthcheck 通过；HTTP 登录和保存读取在重启后保持一致。使用受控 Gateway 的结果只证明应用数据库与 HTTP 集成。
- 清理仅限本次独立项目及卷，生产发布和外部服务验收另记限制。
