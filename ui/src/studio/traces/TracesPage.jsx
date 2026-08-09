'use client';
import TracesMain from './TracesMain.jsx';

// Standalone dock Traces app. The left rail (TracesSidebar, rendered by OsShell) selects a
// session into the shared store; TracesMain renders that session's timeline + steps + detail.
export default function TracesPage() {
  return <TracesMain />;
}
