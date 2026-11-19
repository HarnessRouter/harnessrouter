# Hexa 任务作战台设计

打开 [`index.html`](index.html) 可查看设计板；单页原型和 PNG 见下：

- [`01-tasks-overview.html`](01-tasks-overview.html) / [`PNG`](screens/01-tasks-overview.png)
- [`02-task-detail.html`](02-task-detail.html) / [`PNG`](screens/02-task-human-review.png)
- [`03-runs.html`](03-runs.html) / [`PNG`](screens/03-run-history.png)
- [`04-templates.html`](04-templates.html) / [`PNG`](screens/04-template-library.png)
- [`05-mobile-tasks.html`](05-mobile-tasks.html) / [`PNG`](screens/05-mobile-tasks.png)
- [`06-mobile-detail.html`](06-mobile-detail.html) / [`PNG`](screens/06-mobile-human-review.png)
- [`08-chat.html`](08-chat.html) / [`PNG`](screens/08-chat.png)

我的任务、运行记录和模板管理统一为同一结构：白底、顶部筛选条、单一 table，不按状态或日期插入分组行；数据行铺满主列高度，最后一行贴底。右侧详情采用全高可收缩扩展栏，收起后保留 44px 唤起把手。

我的任务、运行记录和模板管理在 1440px 视口下统一展开为 720px；更窄桌面宽度下三页详情都按 `clamp(400px, 64%, 720px)` 收缩，并保证列表至少保留 280px。三页详情栏都能拖动左边缘改变宽度、分别记忆本页宽度，收起后为 44px 把手；列表按容器宽度渐进隐藏耗时/进度列，运行详情内部再分为执行轨迹与实时事件两列。

三页列表均支持“列表 / 卡片”切换。卡片上方是工作流缩略图，下方是标题、状态/进度和元数据；选中卡片与右侧详情同步。

任务详情、运行记录和模板管理的右侧检查器/详情同样从工作区顶部贯穿到底部，页面标题与操作只占据左侧内容列。

对话页采用“历史 + 会话 + 上下文”三栏：对话历史留在上下文侧栏，主线程展示运行卡片和人工确认，右侧固定 Agent、关联任务、文件、工具与上下文预算；右侧栏可收起为 44px 把手。

总览设计板：[`task-workbench-board.png`](task-workbench-board.png)

完整设计依据、token、断点、状态、实施映射和截图哈希见 [`design-spec.md`](design-spec.md)。

生产 UI 已按本设计实施，实施范围、验证命令与截图证据见 [`CHG-task-workbench-redesign`](../../changes/CHG-task-workbench-redesign/change-record.yaml)。后续修改继续遵守 `docs/changes/CHG-hexa-remove-cloud-contract/spec.md` 的 Hexa 产品边界。
