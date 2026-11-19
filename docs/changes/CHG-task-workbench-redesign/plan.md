# 实施方案

- 行为、边界与验收依据：`spec.md`
- 视觉依据：`docs/design/task-workbench-redesign/design-spec.md`
- 执行记录：`change-record.yaml`

## 方案与依赖

- 应用壳沿用现有 `AppBackendClient` 的 rail、上下文侧栏和主工作区；桌面尺寸对齐设计稿的 64px / 248px。
- 任务管理页统一为一个可复用工作台结构：左侧列表（列表/卡片）、右侧全高详情、可拖拽宽度和 44px 收起把手。三页详情在 1440px 下统一 720px，窄桌面按 `clamp(400px, 64%, 720px)` 收缩并保证列表至少 280px；三页分别记忆拖拽后的宽度。
- 运行记录保留现有 `RunFlowPreview` 和运行属性能力，但改为详情栏中的次级“打开流程图”入口；默认详情展示执行轨迹和实时事件。
- 模板管理保留现有 `Templates` 编辑器；列表和详情改为 table + 全高详情。
- 对话页把主工作区改为 `对话主线程 + 会话上下文` 两列，左侧全局上下文侧栏继续承载对话历史；上下文栏全高并可收起。
- 复用现有 Ant Design 组件、图标和可访问名称，不新增依赖。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 新建本变更的 spec、plan、视觉契约和 change record | 文档自查；引用设计稿和领域契约 |
| 2 | 先新增工作台布局 Playwright 目标测试，确认旧浮层/卡片布局导致 Red | 覆盖 AC-1 至 AC-6 |
| 3 | 重构 `AppTasks.tsx` 为全高列表 + 详情工作台，补样例数据密度和详情内容 | AC-1、AC-2、AC-3、AC-4、AC-7 |
| 4 | 重构 `AppBackendClient.tsx` 对话主区和上下文栏，保留真实消息、附件、Agent 与模型行为 | AC-5、AC-7 |
| 5 | 调整 `styles.css` 应用壳尺寸、工作台分栏、表格、详情栏、对话 composer 和移动端断点 | AC-1 至 AC-6 |
| 6 | 更新受影响的 tasks、run-history、navigation、chat 测试并运行定向 Playwright | AC-1 至 AC-7 |
| 7 | 运行 typecheck、build、客户端单测；生成 1440×900 与 390×844 截图，并在 1280/1024 宽度复核分栏几何 | 完成证据写入 `change-record.yaml` |

## 恢复与收尾

- 本次只修改前端展示与交互；如需回滚，恢复 `client/src/AppTasks.tsx`、`client/src/AppBackendClient.tsx`、`client/src/styles.css` 和对应测试即可。
- 不修改后端数据、迁移、凭据或 Gateway 配置，回滚不涉及数据修复。
- 完成后把稳定的工作台布局与视觉决定保留在 `docs/design/task-workbench-redesign/`；本 Change 保留验证证据和剩余事项。
