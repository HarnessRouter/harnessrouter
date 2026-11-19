# UI 视觉契约

- 设计来源：本目录 spec.md、CHG-chat-reply-details/spec.md 和现有 Hexa 工作台视觉体系；本轮补验刷新恢复与节点过程。
- 平台与视口：Windows Chromium，1440×900 和 390×844，真实 FastAPI/SQLite 与受控 HTTP Gateway。
- 结构与内容：回复详情原位展开在正文上方；节点过程位于运行属性面板，摘要、正文、工具名称/状态分别展示；不展示原始工具参数。
- 状态：恢复运行中的对话应展示已持久化过程；终态须结束“生成中”，读取服务端历史回复并恢复操作；两节点过程互相隔离。
- 响应式：桌面使用运行属性侧栏，390px 使用有界 Drawer。长无空格文本自动换行，页面及过程容器不得横向溢出（允许 1px 浮点测量误差）。
- 验收方法：execution-progress.spec.ts 验证真实 HTTP/SSE、刷新、终态、节点切换、长文本及宽度；截图需实际查看可读性和遮挡。证据在 client/.artifacts/execution-progress/，结论和哈希记入 Change。
- Red/Green 和功能/视觉/advisory/not_evaluated 结论统一见 change-record.yaml；既有概括性 E2E 记录不代替此次新增场景。
