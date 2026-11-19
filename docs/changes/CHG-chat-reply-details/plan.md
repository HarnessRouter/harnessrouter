# 实施方案

- 行为、边界与验收依据：spec.md。
- 执行记录：change-record.yaml。初始局部样式尝试已发生；本方案在补齐跨模块持久化前建立。

## 方案与依赖

复用消息请求幂等记录，新增可空 execution_json 保存每次请求的起始时间、耗时、Harness、模型、公开摘要和工具状态。SQLite 启动兼容旧库，PostgreSQL 增量 SQL 迁移。会话消息按幂等键关联执行详情，流式快照同步当前过程。独立 ReplyDetails 组件以 details/summary 实现原位展开，Markdown 安全渲染摘要。恢复前次误改的右侧 UI。

## 实施与验证

| 步骤 | 改动与依赖 | 验证方式 |
| --- | --- | --- |
| 1 | 追加目标测试，确认现有行为失败 | 耗时单测、Gateway SSE 单测、会话 API 持久化集成、Playwright 原位展开 |
| 2 | Gateway 公开事件归一化及请求执行详情存储 | 相关后端测试及旧库兼容 |
| 3 | 回复组件、样式及撤回误改 | 类型检查、目标 Playwright、桌面/移动截图 |

## 恢复与收尾

回滚本次代码即可；新增可空列可保留，不删除用户记录。最终证据集中记入 change-record.yaml，视觉目标和截图补入 client/docs/visual-contract.md。
