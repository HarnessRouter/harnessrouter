# 实施方案

- 行为、边界与验收依据：spec.md
- 执行记录位置：change-record.yaml

## 方案与依赖

- 新增独立 `hexa-api/` FastAPI 服务，分层为配置、数据库、认证、Gateway Adapter 和业务路由。
- 使用 SQLAlchemy 2.x；生产连接串由 `HEXA_DATABASE_URL` 注入，默认目标为 PostgreSQL。测试通过应用工厂注入隔离数据库和 Gateway fake。
- 使用随机会话 Token 的 HMAC-SHA-256 哈希作为数据库索引；Cookie 设置 `HttpOnly`、`SameSite=Lax`，生产 HTTPS 下由 `HEXA_COOKIE_SECURE` 控制 Secure。
- Gateway Adapter 只调用现有 UHP 读接口，API Key 从后端环境配置读取；不在前端保留 Gateway 凭据。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 建立变更包和认证安全测试骨架 | 先运行目标测试确认有效 Red |
| 2 | 实现配置、数据库模型、会话认证和健康检查 | AC-1 至 AC-4；pytest 单元/接口测试 |
| 3 | 实现 Gateway Adapter、Agent/模型读取和工作空间代理 | AC-5；mock Gateway 集成测试 |
| 4 | 实现会话索引、幂等消息入口和恢复状态 | 对话接口测试；不重复提交验证 |
| 5 | 补充 README、运行配置和 client app 模式适配 | 类型检查、构建、接口回归；不触碰 Gateway |
| 6 | 运行真实本地服务冒烟和安全自查 | 记录环境限制、Provider/CORS 外部阻塞及剩余工作 |
| 7 | 补齐 app Agent 创建、删除确认、列表重读和模型切换 | API 单测、app UI 与真实 HTTP 夹具集成；失败保留、迟到请求和移动布局 |
| 8 | 以 4174 当前 client 源码为 UI 真源，将一级导航提取为共享组件，任务列表和模板编辑器复用同一实现 | App 四模块切换、文字偏好、深色/移动布局；保留 FastAPI 对话链路，未迁移任务执行禁用 |
| 9 | 对话历史独立请求序列；将检查器标题、分区及信息行提取到 ChatInspector.tsx；移除静态入口、Gateway 直连 API、`/v1` 浏览器代理和静态专用测试 | 历史与 Agent 失败隔离、重试和草稿保留；Chromium/Edge 检查 320px 全高、标签、折叠、深色和移动抽屉；唯一入口、App 构建和 FastAPI 集成回归 |

## 恢复与收尾

- 新服务为新增目录，回滚时停止服务并移除 `hexa-api/` 相关变更；不回滚或恢复已移除的 Cloud 能力。
- 本 Change 完成后将验证证据写入 `change-record.yaml`；后端化 Memory、Template、Workflow 继续拆分为后续变更。
