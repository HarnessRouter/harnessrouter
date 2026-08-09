'use client';
// Tasks, the Workspace's execution/observation surface, rendered per the HIG prototype's
// run-layout master-detail: page header (title + harness select + New Task), bordered
// list/detail card, task rows with status chips + updated times, detail head with run-meta,
// Conversation | Trace tabs. One unified list (no Live/Test split, product decision
// 2026-07-18); end-user↔session permission modeling belongs to the host application.
import Workbench from '../workbench/page';

export default function TasksPage() {
  return <Workbench />;
}
