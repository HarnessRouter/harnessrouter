const sprite = `
<svg class="sprite" aria-hidden="true" focusable="false">
  <defs>
    <marker id="flow-arrow" viewBox="0 0 7 7" refX="6" refY="3.5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
      <path d="M0 0.8 6 3.5 0 6.2" fill="none" stroke="#b8c2cf" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <symbol id="i-hex" viewBox="0 0 24 24">
    <path d="M12 2.7 20 7.35v9.3L12 21.3l-8-4.65v-9.3z"/>
    <path d="M8.6 8.2v7.6M15.4 8.2v7.6M8.6 12h6.8"/>
  </symbol>
  <symbol id="i-grid" viewBox="0 0 24 24">
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/>
    <rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/>
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/>
    <rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>
  </symbol>
  <symbol id="i-message" viewBox="0 0 24 24">
    <path d="M20.5 11.4a8.1 8.1 0 0 1-8.2 7.9 8.8 8.8 0 0 1-3.2-.6L4 20.3l1.6-4.4a7.7 7.7 0 0 1-.9-3.7 8.1 8.1 0 0 1 8.2-7.9 8.1 8.1 0 0 1 7.6 7.1Z"/>
    <path d="M8.5 10.2h7M8.5 13.5h4.8"/>
  </symbol>
  <symbol id="i-tasks" viewBox="0 0 24 24">
    <rect x="4" y="3.5" width="16" height="17" rx="2.7"/>
    <path d="m8 8.2 1.3 1.4L12 6.8M14.5 8.5h2M8 13.3l1.3 1.4 2.7-2.8M14.5 13.6h2M8 18h8.5"/>
  </symbol>
  <symbol id="i-agent" viewBox="0 0 24 24">
    <path d="M12 3.3 13.6 8l4.7 1.6-4.7 1.6L12 15.9l-1.6-4.7L5.7 9.6 10.4 8z"/>
    <path d="m18.6 15 .7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7zM5.3 15.7l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5z"/>
  </symbol>
  <symbol id="i-settings" viewBox="0 0 24 24">
    <circle cx="12" cy="12" r="3"/>
    <path d="M19.3 15.1a1.7 1.7 0 0 0 .3 1.9l.1.1-2.6 2.6-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.2h-3.7v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1-2.6-2.6.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H4v-3.7h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 2.6-2.6.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5v-.2h3.7v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1 2.6 2.6-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.2v3.7h-.2a1.7 1.7 0 0 0-1.5 1Z"/>
  </symbol>
  <symbol id="i-moon" viewBox="0 0 24 24">
    <path d="M20 15.2A8.5 8.5 0 0 1 8.8 4a8.6 8.6 0 1 0 11.2 11.2Z"/>
  </symbol>
  <symbol id="i-search" viewBox="0 0 24 24">
    <circle cx="10.8" cy="10.8" r="6.5"/>
    <path d="m15.6 15.6 4.1 4.1"/>
  </symbol>
  <symbol id="i-plus" viewBox="0 0 24 24">
    <path d="M12 5v14M5 12h14"/>
  </symbol>
  <symbol id="i-chevron-down" viewBox="0 0 24 24">
    <path d="m7 9.5 5 5 5-5"/>
  </symbol>
  <symbol id="i-chevron-right" viewBox="0 0 24 24">
    <path d="m9.5 6.5 5.5 5.5-5.5 5.5"/>
  </symbol>
  <symbol id="i-chevron-left" viewBox="0 0 24 24">
    <path d="M14.5 6.5 9 12l5.5 5.5"/>
  </symbol>
  <symbol id="i-filter" viewBox="0 0 24 24">
    <path d="M4 6h16M7 12h10M10 18h4"/>
  </symbol>
  <symbol id="i-more" viewBox="0 0 24 24">
    <circle cx="5.5" cy="12" r="1" fill="currentColor" stroke="none"/>
    <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/>
    <circle cx="18.5" cy="12" r="1" fill="currentColor" stroke="none"/>
  </symbol>
  <symbol id="i-bell" viewBox="0 0 24 24">
    <path d="M18 9.8a6 6 0 0 0-12 0c0 6.4-2.2 6.5-2.2 7.7h16.4c0-1.2-2.2-1.3-2.2-7.7Z"/>
    <path d="M10 20h4"/>
  </symbol>
  <symbol id="i-check" viewBox="0 0 24 24">
    <path d="m5 12.5 4.3 4.3L19 7"/>
  </symbol>
  <symbol id="i-clock" viewBox="0 0 24 24">
    <circle cx="12" cy="12" r="8.5"/>
    <path d="M12 7.2V12l3.3 2"/>
  </symbol>
  <symbol id="i-alert" viewBox="0 0 24 24">
    <path d="M10.3 4.1 3.5 16a2 2 0 0 0 1.7 3h13.6a2 2 0 0 0 1.7-3L13.7 4.1a2 2 0 0 0-3.4 0Z"/>
    <path d="M12 9v4.5M12 17h.01"/>
  </symbol>
  <symbol id="i-play" viewBox="0 0 24 24">
    <path d="m9 6.5 8 5.5-8 5.5z"/>
  </symbol>
  <symbol id="i-pause" viewBox="0 0 24 24">
    <path d="M8.5 6v12M15.5 6v12"/>
  </symbol>
  <symbol id="i-stop" viewBox="0 0 24 24">
    <rect x="6.5" y="6.5" width="11" height="11" rx="1.8"/>
  </symbol>
  <symbol id="i-refresh" viewBox="0 0 24 24">
    <path d="M19.5 9a8 8 0 0 0-13.8-2L3.5 9.6M4.5 15a8 8 0 0 0 13.8 2l2.2-2.6"/>
    <path d="M3.5 4.8v4.8h4.8M20.5 19.2v-4.8h-4.8"/>
  </symbol>
  <symbol id="i-shield" viewBox="0 0 24 24">
    <path d="M12 3.2c2.5 1.7 4.9 2.6 7.1 2.9v5.4c0 4.2-2.4 7.3-7.1 9.3-4.7-2-7.1-5.1-7.1-9.3V6.1C7.1 5.8 9.5 4.9 12 3.2Z"/>
    <path d="m8.8 12 2.2 2.2 4.3-4.4"/>
  </symbol>
  <symbol id="i-target" viewBox="0 0 24 24">
    <circle cx="12" cy="12" r="8.3"/>
    <circle cx="12" cy="12" r="4.5"/>
    <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/>
  </symbol>
  <symbol id="i-terminal" viewBox="0 0 24 24">
    <rect x="3" y="4.5" width="18" height="15" rx="2.4"/>
    <path d="m7 9 3 3-3 3M12.5 15h4"/>
  </symbol>
  <symbol id="i-server" viewBox="0 0 24 24">
    <rect x="4" y="3.5" width="16" height="7" rx="1.8"/>
    <rect x="4" y="13.5" width="16" height="7" rx="1.8"/>
    <path d="M7.5 7h.01M7.5 17h.01M11 7h5.5M11 17h5.5"/>
  </symbol>
  <symbol id="i-globe" viewBox="0 0 24 24">
    <circle cx="12" cy="12" r="8.5"/>
    <path d="M3.7 12h16.6M12 3.5c2.2 2.3 3.3 5.1 3.3 8.5S14.2 18.2 12 20.5C9.8 18.2 8.7 15.4 8.7 12S9.8 5.8 12 3.5Z"/>
  </symbol>
  <symbol id="i-doc" viewBox="0 0 24 24">
    <path d="M6 3.5h8l4 4v13H6z"/>
    <path d="M14 3.5v4h4M9 12h6M9 15.5h6"/>
  </symbol>
  <symbol id="i-chart" viewBox="0 0 24 24">
    <path d="M4 19.5V5M4 19.5h16"/>
    <path d="m7.5 15 3.2-3.5 3.1 2.1 4.7-6"/>
  </symbol>
  <symbol id="i-layers" viewBox="0 0 24 24">
    <path d="m12 3.5 8.5 4.4L12 12.3 3.5 7.9z"/>
    <path d="m4.2 12 7.8 4.1 7.8-4.1M4.2 16 12 20.1l7.8-4.1"/>
  </symbol>
  <symbol id="i-file-stack" viewBox="0 0 24 24">
    <path d="M8 3.5h7l3 3v10H8z"/>
    <path d="M8 19.5H5.5v-13H11l2 2"/>
    <path d="M15 3.5v3h3M11 10h4M11 13h4"/>
  </symbol>
  <symbol id="i-eye" viewBox="0 0 24 24">
    <path d="M3.5 12s3.1-5.2 8.5-5.2 8.5 5.2 8.5 5.2-3.1 5.2-8.5 5.2S3.5 12 3.5 12Z"/>
    <circle cx="12" cy="12" r="2.3"/>
  </symbol>
  <symbol id="i-zoom-in" viewBox="0 0 24 24">
    <circle cx="10.5" cy="10.5" r="6.3"/>
    <path d="m15.2 15.2 4.3 4.3M10.5 7.5v6M7.5 10.5h6"/>
  </symbol>
  <symbol id="i-zoom-out" viewBox="0 0 24 24">
    <circle cx="10.5" cy="10.5" r="6.3"/>
    <path d="m15.2 15.2 4.3 4.3M7.5 10.5h6"/>
  </symbol>
  <symbol id="i-fit" viewBox="0 0 24 24">
    <path d="M8.5 4H4v4.5M15.5 4H20v4.5M20 15.5V20h-4.5M8.5 20H4v-4.5"/>
  </symbol>
  <symbol id="i-layout" viewBox="0 0 24 24">
    <rect x="3.5" y="4" width="17" height="16" rx="2"/>
    <path d="M3.5 9h17M9.5 9v11"/>
  </symbol>
  <symbol id="i-bolt" viewBox="0 0 24 24">
    <path d="m13.2 2.8-7 10.1h5.4l-.8 8.3 7-10.6h-5.3z"/>
  </symbol>
  <symbol id="i-arrow-right" viewBox="0 0 24 24">
    <path d="M5 12h14M13.5 6.5 19 12l-5.5 5.5"/>
  </symbol>
  <symbol id="i-arrow-left" viewBox="0 0 24 24">
    <path d="M19 12H5M10.5 6.5 5 12l5.5 5.5"/>
  </symbol>
  <symbol id="i-branch" viewBox="0 0 24 24">
    <circle cx="6" cy="5.5" r="2"/>
    <circle cx="18" cy="7.5" r="2"/>
    <circle cx="6" cy="18.5" r="2"/>
    <path d="M6 7.5v9M8 6.3c4.5 0 3.6 1.2 8 1.2"/>
  </symbol>
  <symbol id="i-lock" viewBox="0 0 24 24">
    <rect x="5" y="10" width="14" height="10" rx="2.2"/>
    <path d="M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10M12 14v2.2"/>
  </symbol>
  <symbol id="i-drag" viewBox="0 0 24 24">
    <circle cx="8" cy="7" r="1" fill="currentColor" stroke="none"/>
    <circle cx="16" cy="7" r="1" fill="currentColor" stroke="none"/>
    <circle cx="8" cy="12" r="1" fill="currentColor" stroke="none"/>
    <circle cx="16" cy="12" r="1" fill="currentColor" stroke="none"/>
    <circle cx="8" cy="17" r="1" fill="currentColor" stroke="none"/>
    <circle cx="16" cy="17" r="1" fill="currentColor" stroke="none"/>
  </symbol>
  <symbol id="i-expand" viewBox="0 0 24 24">
    <path d="M9 4H4v5M15 4h5v5M20 15v5h-5M4 15v5h5"/>
  </symbol>
  <symbol id="i-star" viewBox="0 0 24 24">
    <path d="m12 3.8 2.5 5.1 5.6.8-4.1 4 1 5.6-5-2.6-5 2.6 1-5.6-4.1-4 5.6-.8z"/>
  </symbol>
  <symbol id="i-link" viewBox="0 0 24 24">
    <path d="M9.5 14.5 14.5 9.5M8.2 17.8l-1.6 1.6a3.7 3.7 0 0 1-5.2-5.2l3.4-3.4a3.7 3.7 0 0 1 5.2 0M15.8 6.2l1.6-1.6a3.7 3.7 0 0 1 5.2 5.2l-3.4 3.4a3.7 3.7 0 0 1-5.2 0"/>
  </symbol>
</svg>`;

document.body.insertAdjacentHTML('afterbegin', sprite);

function railMarkup(active = 'tasks') {
  const railActive = active === 'chat' ? 'chat' : 'tasks';
  return `
<aside class="rail" aria-label="主导航">
  <div class="rail-brand" aria-label="Hexa">
    <span class="brand-mark"><svg class="icon"><use href="#i-hex"></use></svg></span>
  </div>
  <nav class="rail-nav" aria-label="主要功能">
    <button class="rail-button${railActive === 'tasks' ? ' is-active' : ''}" type="button" aria-label="任务"><svg class="icon"><use href="#i-tasks"></use></svg></button>
    <button class="rail-button${railActive === 'chat' ? ' is-active' : ''}" type="button" aria-label="对话"><svg class="icon"><use href="#i-message"></use></svg></button>
    <button class="rail-button" type="button" aria-label="智能体"><svg class="icon"><use href="#i-agent"></use></svg></button>
    <button class="rail-button" type="button" aria-label="应用"><svg class="icon"><use href="#i-grid"></use></svg></button>
  </nav>
  <div class="rail-divider"></div>
  <nav class="rail-nav" aria-label="辅助功能">
    <button class="rail-button" type="button" aria-label="通知"><svg class="icon"><use href="#i-bell"></use></svg></button>
  </nav>
  <div class="rail-spacer"></div>
  <div class="rail-bottom">
    <button class="rail-button" type="button" aria-label="设置"><svg class="icon"><use href="#i-settings"></use></svg></button>
    <button class="rail-button" type="button" aria-label="切换主题"><svg class="icon"><use href="#i-moon"></use></svg></button>
    <span class="rail-status" title="本地服务正常"></span>
    <span class="rail-avatar" aria-label="用户 A">A</span>
  </div>
</aside>`;
}

function sidebarMarkup(active) {
  const isActive = (name) => (active === name ? ' is-active' : '');
  if (active === 'chat') {
    return `
  <aside class="sidebar chat-sidebar" aria-label="对话侧栏">
    <button class="workspace-switch" type="button" aria-label="切换工作区">
      <span class="workspace-icon">H</span>
      <span class="workspace-copy"><small>当前工作区</small><strong>Hexa 工作空间</strong></span>
      <svg class="icon"><use href="#i-chevron-down"></use></svg>
    </button>
    <button class="new-task-button chat-new-button" type="button" aria-label="新建对话">
      <span class="new-task-plus"><svg class="icon"><use href="#i-plus"></use></svg></span>
      <span class="new-task-copy"><strong>新建对话</strong><small>选择 Agent 或直接开始</small></span>
      <kbd>N</kbd>
    </button>
    <label class="side-search" aria-label="搜索对话">
      <svg class="icon"><use href="#i-search"></use></svg>
      <span>搜索对话</span>
      <kbd>⌘K</kbd>
    </label>
    <nav class="side-nav chat-history" aria-label="对话历史">
      <p class="side-label">今天</p>
      <button class="chat-history-item is-active" type="button">
        <span class="chat-history-icon blue"><svg class="icon"><use href="#i-shield"></use></svg></span>
        <span class="chat-history-copy"><strong>安全事件调查</strong><small>调查分析师 · 2 分钟前</small></span>
      </button>
      <button class="chat-history-item" type="button">
        <span class="chat-history-icon"><svg class="icon"><use href="#i-message"></use></svg></span>
        <span class="chat-history-copy"><strong>客服工单归因</strong><small>客服运营 · 18 分钟前</small></span>
      </button>
      <button class="chat-history-item" type="button">
        <span class="chat-history-icon"><svg class="icon"><use href="#i-chart"></use></svg></span>
        <span class="chat-history-copy"><strong>竞品市场研究</strong><small>市场研究员 · 1 小时前</small></span>
      </button>
      <p class="side-label" style="margin-top:14px">昨天</p>
      <button class="chat-history-item" type="button">
        <span class="chat-history-icon"><svg class="icon"><use href="#i-layers"></use></svg></span>
        <span class="chat-history-copy"><strong>产品方案评估</strong><small>产品分析师 · 昨天</small></span>
      </button>
      <button class="chat-history-item" type="button">
        <span class="chat-history-icon"><svg class="icon"><use href="#i-doc"></use></svg></span>
        <span class="chat-history-copy"><strong>周报自动汇编</strong><small>内容助理 · 昨天</small></span>
      </button>
      <button class="chat-history-item" type="button">
        <span class="chat-history-icon"><svg class="icon"><use href="#i-file-stack"></use></svg></span>
        <span class="chat-history-copy"><strong>供应商风险评估</strong><small>风险顾问 · 昨天</small></span>
      </button>
      <p class="side-label" style="margin-top:14px">更早</p>
      <button class="chat-history-item" type="button">
        <span class="chat-history-icon"><svg class="icon"><use href="#i-terminal"></use></svg></span>
        <span class="chat-history-copy"><strong>代码仓库巡检</strong><small>工程助手 · 11月15日</small></span>
      </button>
    </nav>
    <div class="side-spacer"></div>
    <div class="side-foot"><span class="status-dot"></span><span>本地 API 已连接 · 运行正常</span></div>
  </aside>`;
  }
  return `
  <aside class="sidebar" aria-label="任务侧栏">
    <button class="workspace-switch" type="button" aria-label="切换工作区">
      <span class="workspace-icon">H</span>
      <span class="workspace-copy"><small>当前工作区</small><strong>Hexa 工作空间</strong></span>
      <svg class="icon"><use href="#i-chevron-down"></use></svg>
    </button>
    <button class="new-task-button" type="button" aria-label="新建任务">
      <span class="new-task-plus"><svg class="icon"><use href="#i-plus"></use></svg></span>
      <span class="new-task-copy"><strong>新建任务</strong><small>从空白或模板开始</small></span>
      <kbd>N</kbd>
    </button>
    <nav class="side-nav" aria-label="任务导航">
      <p class="side-label">任务工作区</p>
      <button class="side-link${isActive('tasks')}" type="button"><svg class="icon"><use href="#i-tasks"></use></svg><span>我的任务</span><span class="side-count">8</span></button>
      <button class="side-link${isActive('runs')}" type="button"><svg class="icon"><use href="#i-clock"></use></svg><span>运行记录</span><span class="side-count">12</span></button>
      <button class="side-link${isActive('templates')}" type="button"><svg class="icon"><use href="#i-layers"></use></svg><span>模板库</span><span class="side-count">8</span></button>
      <p class="side-label" style="margin-top:14px">最近访问</p>
      <button class="recent-link" type="button"><span class="status-dot amber"></span><span>安全事件调查</span><time>刚刚</time></button>
      <button class="recent-link" type="button"><span class="status-dot blue"></span><span>客服工单归因</span><time>1 分钟</time></button>
      <button class="recent-link" type="button"><span class="status-dot green"></span><span>产品方案评估</span><time>昨天</time></button>
      <button class="recent-link" type="button"><span class="status-dot gray"></span><span>Q3 复盘材料</span><time>11月15日</time></button>
    </nav>
    <div class="side-spacer"></div>
    <button class="side-note" type="button">
      <span class="side-note-icon"><svg class="icon"><use href="#i-alert"></use></svg></span>
      <span class="side-note-copy"><strong>1 项等待确认</strong><span>安全事件调查 · 已等待 12 分钟</span></span>
      <svg class="icon"><use href="#i-chevron-right"></use></svg>
    </button>
    <div class="side-foot"><span class="status-dot"></span><span>本地 API 已连接 · 运行正常</span></div>
  </aside>`;
}

document.querySelectorAll('[data-shell]').forEach((app) => {
  const active = app.dataset.active || 'tasks';
  app.insertAdjacentHTML('afterbegin', railMarkup(active) + sidebarMarkup(active));
});

document.querySelectorAll('[data-rail-only]').forEach((app) => {
  app.insertAdjacentHTML('afterbegin', railMarkup('tasks'));
});

const flowVariants = {
  incident: {
    labels: ['告警', '狩猎', '取证', '资产', '情报'],
    gate: '确认',
    summary: '汇总',
    validateA: '校验 A',
    validateB: '校验 B',
    report: '报告'
  },
  market: {
    labels: ['公开资料', '财报', '渠道', '舆情', '评论'],
    gate: '筛选',
    summary: '归纳',
    validateA: '事实',
    validateB: '风险',
    report: '报告'
  },
  product: {
    labels: ['产品', '技术', '风险', '用户', '市场'],
    gate: '评审',
    summary: '汇总',
    validateA: '校验 A',
    validateB: '校验 B',
    report: '决策'
  },
  research: {
    labels: ['收集', '清洗', '核验', '引用', '归档'],
    gate: '确认',
    summary: '整理',
    validateA: '事实',
    validateB: '合规',
    report: '报告'
  },
  risk: {
    labels: ['财务', '法务', '供应', '舆情', '合规'],
    gate: '评分',
    summary: '汇总',
    validateA: '复核 A',
    validateB: '复核 B',
    report: '报告'
  },
  digest: {
    labels: ['来源', '筛选', '摘要', '校对', '排版'],
    gate: '审核',
    summary: '汇编',
    validateA: '事实',
    validateB: '风格',
    report: '周报'
  }
};

function compactFlow(name) {
  const variant = flowVariants[name] || flowVariants.incident;
  const xs = [0, 62];
  const ys = [4, 21, 38, 55, 72];
  const collectorEdges = ys
    .map((y) => `<path class="flow-edge done" d="M62 ${y + 6} C78 ${y + 6} 78 46 94 46"/>`)
    .join('');
  const collectors = ys
    .map(
      (y, index) => `
      <rect class="flow-box done" x="${xs[0]}" y="${y}" width="62" height="12" rx="4"/>
      <circle cx="8" cy="${y + 6}" r="2.1" fill="#12b76a"/>
      <text class="flow-label done" x="35" y="${y + 8.2}">${variant.labels[index]}</text>`
    )
    .join('');
  return `
  <svg class="flow-svg" viewBox="0 0 340 92" role="img" aria-label="工作流缩略图：五个并行节点汇聚到人工门控，再进入汇总、双校验和报告">
    ${collectorEdges}
    ${collectors}
    <path class="flow-edge active" d="M138 46 H164"/>
    <path class="flow-edge future" d="M210 46 C222 46 224 28 236 28"/>
    <path class="flow-edge future" d="M210 46 C222 46 224 64 236 64"/>
    <path class="flow-edge future" d="M278 28 C290 28 290 46 302 46"/>
    <path class="flow-edge future" d="M278 64 C290 64 290 46 302 46"/>
    <rect class="flow-box waiting" x="94" y="33" width="44" height="26" rx="5"/>
    <text class="flow-label waiting" x="116" y="49">${variant.gate}</text>
    <rect class="flow-box future" x="164" y="33" width="46" height="26" rx="5"/>
    <text class="flow-label" x="187" y="49">${variant.summary}</text>
    <rect class="flow-box future" x="236" y="18" width="42" height="20" rx="4"/>
    <text class="flow-label" x="257" y="30.5">${variant.validateA}</text>
    <rect class="flow-box future" x="236" y="54" width="42" height="20" rx="4"/>
    <text class="flow-label" x="257" y="66.5">${variant.validateB}</text>
    <rect class="flow-box future" x="302" y="33" width="34" height="26" rx="5"/>
    <text class="flow-label" x="319" y="49">${variant.report}</text>
  </svg>`;
}

function detailedSecurityFlow() {
  const labels = ['告警分析', '威胁狩猎', '日志取证', '资产核查', '情报检索'];
  const ys = [4, 28, 52, 76, 100];
  return `
  <svg class="flow-svg" viewBox="0 0 340 128" role="img" aria-label="安全事件调查工作流：五个调查节点并行，结果进入人工确认，再进入汇总、双校验和最终报告">
    <path class="flow-edge done" d="M63 12.5 C78 12.5 78 63 94 63"/>
    <path class="flow-edge done" d="M63 36.5 C78 36.5 78 63 94 63"/>
    <path class="flow-edge done" d="M63 60.5 H94"/>
    <path class="flow-edge done" d="M63 84.5 C78 84.5 78 63 94 63"/>
    <path class="flow-edge done" d="M63 108.5 C78 108.5 78 63 94 63"/>
    <path class="flow-edge active" d="M138 63 H166"/>
    <path class="flow-edge future" d="M214 63 C228 63 230 37 242 37"/>
    <path class="flow-edge future" d="M214 63 C228 63 230 89 242 89"/>
    <path class="flow-edge future" d="M286 37 C296 37 294 63 302 63"/>
    <path class="flow-edge future" d="M286 89 C296 89 294 63 302 63"/>
    ${ys
      .map(
        (y, index) => `
      <rect class="flow-box done" x="0" y="${y}" width="63" height="17" rx="4.5"/>
      <circle cx="9" cy="${y + 8.5}" r="2.4" fill="#12b76a"/>
      <text class="flow-label done" x="38" y="${y + 10.6}">${labels[index]}</text>`
      )
      .join('')}
    <rect class="flow-box waiting" x="94" y="48" width="44" height="30" rx="5.5"/>
    <text class="flow-label waiting" x="116" y="62">人工确认</text>
    <text class="flow-sub" x="116" y="71.5">已选 2 / 5</text>
    <rect class="flow-box future" x="166" y="48" width="48" height="30" rx="5.5"/>
    <text class="flow-label" x="190" y="65">汇总调查</text>
    <rect class="flow-box future" x="242" y="26" width="44" height="22" rx="4.5"/>
    <text class="flow-label" x="264" y="39.6">校验 A</text>
    <rect class="flow-box future" x="242" y="78" width="44" height="22" rx="4.5"/>
    <text class="flow-label" x="264" y="91.6">校验 B</text>
    <rect class="flow-box future" x="302" y="49" width="34" height="28" rx="5"/>
    <text class="flow-label" x="319" y="65.5">报告</text>
  </svg>`;
}

document.querySelectorAll('[data-flow]').forEach((container) => {
  container.innerHTML = compactFlow(container.dataset.flow);
});

document.querySelectorAll('[data-security-flow]').forEach((container) => {
  container.innerHTML = detailedSecurityFlow();
});
