# 实施方案

- 行为、边界与验收依据：spec.md
- 执行记录位置：change-record.yaml

## 方案与依赖

- 扩展现有 AppAgentsPanel：Agent/模板库页内导航、来源筛选、搜索、统一视图偏好、模板表单与确认操作。
- 新建 agent_templates 表和独立 router，避免与任务模板耦合；复用应用会话、用户 ID 和数据库工厂。提供 PostgreSQL 增量 SQL，SQLite 测试自动建表。
- Gateway Adapter 只读现有 `/v1/bases`，白名单映射基本字段与可用状态。客户模板独立 API 保证上游故障不阻塞客户数据。
- 先写持久化、代理契约、UI 流程测试并确认 Red，再实现。复用现有 Agent 创建/删除和会话回归。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 记录契约与目标测试 | pytest/API 单测/Playwright 目标 Red |
| 2 | 模板模型、CRUD 和 Gateway bases 映射 | 隔离 SQLite 与 HTTP Adapter 测试、用户边界和安全错误 |
| 3 | 模板库、表单与双视图 | Chromium/Edge UI、新建/编辑/复制/使用/删除/失败恢复 |
| 4 | 完整服务边界和视觉自查 | HTTP Gateway + FastAPI + 浏览器集成、桌面/移动/深色截图，类型与构建 |

## 恢复与收尾

- 回滚本次客户端入口与新增 router，停止使用 agent_templates 表；表为独立新增且不影响现有 Agent/任务数据。生产增量迁移由部署流程执行，本次不部署。
- 保留 spec 为 Agent 模板契约，plan 为实施依据；实际结果与限制统一记录 Change。
