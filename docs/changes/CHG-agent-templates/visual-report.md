# Agent 管理视觉验收

2026-11-17；基线 `31d60df5c51cf730b832b8ad596595a4683cb8e3` + 本次工作树；Windows Chromium/Edge。设计依据与实施前目标见 visual-contract.md；实际命令和各层结果见 change-record.yaml。

| 状态 | 视口 | 截图 | SHA-256 |
| --- | --- | --- | --- |
| 卡片 | 1440×900 | `C:/Users/Administrator/AppData/Local/Temp/hexa-agent-templates-cards.png` | `1AD7C2E18C87BDC5EA0CC84C65D51B9BBA4A2E2D9EFEA3865659C263C1DCAE07` |
| 列表 | 1440×900 | `C:/Users/Administrator/AppData/Local/Temp/hexa-agent-templates-list.png` | `BB802FE0ED997C370396B22B74BC5339A53FD9D6B856DB654F1BE6BEB347D466` |
| 深色列表 | 1440×900 | `C:/Users/Administrator/AppData/Local/Temp/hexa-agent-templates-dark.png` | `70DFB30DD259F4E7DBC0A6662B7DD61030CBE3DF55C7E39DB73EAF3DD7C6DDC3` |
| 移动深色列表 | 390×844 | `C:/Users/Administrator/AppData/Local/Temp/hexa-agent-templates-mobile.png` | `22B5990014FBC5E4A474D1B079E190F7FF45ED94B0BB39019AFA10B3565FF589` |

- 功能：passed。新建/编辑/复制/使用/删除、失败保留与重试、独立来源、视图记忆、会话过期清理通过。
- 结构与视觉：passed。桌面卡片并列、列表单列纵向排列（boundingBox 断言）；来源/模型/运行时清晰；禁用模板有原因。移动搜索整行、操作换行、长模型名换行，文档宽度 390px；深色使用 hx tokens。截图已分别检查卡片、列表和移动。
- 可访问性：passed。显式表单标签、控件角色名称、tab 方向键/Home/End、焦点、视图 aria-pressed、错误 alert 与 Modal 确认。
- Advisory：生产 JS chunk 大于 500 kB，现有单包构建方式仍有 Vite 提示；不影响本次操作。
- not_evaluated：移动真机、生产 Linux/PostgreSQL 与真实 Gateway；不以桌面视口/HTTP 夹具结果替代。
