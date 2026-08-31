import './styles.css';

const app = document.querySelector('#app');

const icons = {
  grid: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg>',
  briefcase: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="7.5" width="17" height="12.5" rx="2"/><path d="M8.5 7.5V6a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1.5M3.5 12.5h17M10 12.5v2h4v-2"/></svg>',
  file: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4M9 12h6M9 15.5h6"/></svg>',
  activity: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16.5h3l2-6 3.5 9 2.5-6H20"/><path d="M4 5.5h16"/></svg>',
  settings: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"/><path d="m19.4 15 .1.1a1.8 1.8 0 1 1-2.5 2.5l-.1-.1a1.8 1.8 0 0 0-3.1 1.2v.3a1.8 1.8 0 1 1-3.6 0v-.2a1.8 1.8 0 0 0-3.1-1.3l-.1.1a1.8 1.8 0 1 1-2.5-2.5l.1-.1A1.8 1.8 0 0 0 3.4 12a1.8 1.8 0 1 1 0-3.6h.2a1.8 1.8 0 0 0 1.3-3.1l-.1-.1a1.8 1.8 0 1 1 2.5-2.5l.1.1A1.8 1.8 0 0 0 10.5 1.6v-.2a1.8 1.8 0 1 1 3.6 0v.2a1.8 1.8 0 0 0 3.1 1.3l.1-.1a1.8 1.8 0 1 1 2.5 2.5l-.1.1A1.8 1.8 0 0 0 20.5 8h.2a1.8 1.8 0 1 1 0 3.6h-.2a1.8 1.8 0 0 0-1.1 3.4Z"/></svg>',
  chevron: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6"/></svg>',
  external: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8"/><path d="M18 13v5.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H11"/></svg>',
  plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.3"/><path d="m16 16 4.2 4.2"/></svg>',
  bell: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>',
  check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>',
  clock: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/></svg>',
  link: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13.8a4 4 0 0 0 5.7.1l2.2-2.2a4 4 0 0 0-5.7-5.7l-1.3 1.3"/><path d="M14 10.2a4 4 0 0 0-5.7-.1l-2.2 2.2a4 4 0 0 0 5.7 5.7l1.3-1.3"/></svg>',
  shield: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 19 6v5c0 4.7-3 8.2-7 10-4-1.8-7-5.3-7-10V6z"/><path d="m9 12 2 2 4-4"/></svg>',
  sparkle: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6zM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z"/></svg>',
  upload: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4M8 8l4-4 4 4M5 13v5.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V13"/></svg>',
  close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>',
  download: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M8 11l4 4 4-4M5 19h14"/></svg>',
  info: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 10.5v5M12 7.5h.01"/></svg>',
  menu: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'
};

const icon = (name, className = '') => `<span class="icon ${className}">${icons[name] || ''}</span>`;
const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

const state = {
  activeNav: 'overview',
  selectedJob: null,
  modal: null,
  filter: 'All',
  safeMode: true,
  toast: null,
  handoffPrompt: '',
  handoffPending: false,
  handoffInserted: false,
  generating: false,
  mobileNav: false,
  jobs: [
    {
      id: 'nexa',
      company: 'Nexa Systems',
      initials: 'NS',
      color: 'blue',
      title: 'Full-Stack Software Engineer',
      location: 'Abu Dhabi, UAE · Hybrid',
      posted: '18 min ago',
      source: 'Indeed',
      score: 94,
      status: 'Ready to tailor',
      tags: ['Next.js', 'TypeScript', 'AWS'],
      description: 'We are looking for a Full-Stack Software Engineer to build customer-facing products with Next.js and TypeScript. You will design REST APIs, work with PostgreSQL and AWS, and partner with product and design. Experience with AI integrations, testing, and shipping production software is a plus.',
      highlights: ['Next.js + TypeScript', 'PostgreSQL and AWS', 'AI product experience'],
      workflow: 1
    },
    {
      id: 'cloudnest',
      company: 'CloudNest',
      initials: 'CN',
      color: 'purple',
      title: 'Frontend Engineer',
      location: 'Dubai, UAE · On-site',
      posted: '42 min ago',
      source: 'Indeed',
      score: 89,
      status: 'Resume ready',
      tags: ['React', 'JavaScript', 'CSS'],
      description: 'CloudNest is hiring a Frontend Engineer to create accessible, high-performance web experiences in React. The role partners closely with backend engineers and designers. Strong JavaScript, CSS, responsive UI, and REST API experience required.',
      highlights: ['React + JavaScript', 'Accessible UI', 'REST API experience'],
      workflow: 3
    },
    {
      id: 'finloop',
      company: 'Finloop',
      initials: 'FL',
      color: 'orange',
      title: 'Product Engineer, AI',
      location: 'Remote · UAE',
      posted: '1 hr ago',
      source: 'Company site',
      score: 86,
      status: 'Needs review',
      tags: ['Python', 'LLMs', 'Supabase'],
      description: 'Finloop is building a modern financial operations platform. Join a small team working across Python services, LLM workflows, data modeling, and product experiments. We value thoughtful guardrails, clear communication, and a bias toward shipping.',
      highlights: ['LLM workflows', 'Financial products', 'Human-in-the-loop systems'],
      workflow: 1
    },
    {
      id: 'pixelworks',
      company: 'Pixelworks',
      initials: 'PW',
      color: 'green',
      title: 'Software Engineer I',
      location: 'Abu Dhabi, UAE · Hybrid',
      posted: '2 hrs ago',
      source: 'Indeed',
      score: 81,
      status: 'Captured',
      tags: ['Node.js', 'SQL', 'Docker'],
      description: 'Software Engineer I joining a product engineering group. Build Node.js services, maintain SQL data models, contribute to Dockerized deployments, and learn from senior engineers in an agile team.',
      highlights: ['Node.js services', 'SQL data models', 'Docker deployments'],
      workflow: 0
    }
  ],
  activity: [
    { icon: 'check', tone: 'mint', title: 'PDF prepared for CloudNest', detail: 'Frontend Engineer · Resume v3', time: 'Today, 10:42 AM' },
    { icon: 'sparkle', tone: 'lavender', title: 'Resume tailored for Nexa Systems', detail: '6 keywords added · 94% match', time: 'Today, 10:36 AM' },
    { icon: 'briefcase', tone: 'orange', title: 'New job captured from Indeed', detail: 'Full-Stack Software Engineer · Nexa Systems', time: 'Today, 10:21 AM' },
    { icon: 'link', tone: 'blue', title: 'Indeed connection synced', detail: '4 new roles found in your search', time: 'Today, 10:18 AM' }
  ]
};

const navItems = [
  ['overview', 'Overview', 'grid'],
  ['jobs', 'Job queue', 'briefcase'],
  ['resume', 'Resume studio', 'file'],
  ['activity', 'Activity', 'activity']
];

function statusClass(status) {
  if (status.includes('ready')) return 'ready';
  if (status.includes('review')) return 'review';
  if (status.includes('tailor')) return 'tailor';
  return 'captured';
}

function companyMark(job, small = false) {
  return `<span class="company-mark ${job.color} ${small ? 'small-mark' : ''}">${escapeHtml(job.initials)}</span>`;
}

function scoreRing(score, compact = false) {
  const circumference = 2 * Math.PI * 18;
  const offset = circumference - (score / 100) * circumference;
  return `<span class="score-ring ${compact ? 'compact' : ''}" style="--score-offset:${offset}px;--score-color:${score >= 90 ? '#1b9a76' : score >= 85 ? '#6c5ce7' : '#e7a449'}"><svg viewBox="0 0 44 44"><circle class="ring-bg" cx="22" cy="22" r="18"/><circle class="ring-value" cx="22" cy="22" r="18"/></svg><b>${score}</b></span>`;
}

function jobRow(job) {
  return `<button class="job-row ${state.selectedJob === job.id ? 'is-selected' : ''}" data-job="${job.id}">
    ${companyMark(job)}
    <span class="job-row-main">
      <strong>${escapeHtml(job.title)}</strong>
      <span>${escapeHtml(job.company)} <i>·</i> ${escapeHtml(job.location.split(' · ')[0])}</span>
    </span>
    <span class="job-row-meta"><span class="posted">${escapeHtml(job.posted)}</span>${scoreRing(job.score, true)}</span>
    <span class="job-row-arrow">${icon('arrow')}</span>
  </button>`;
}

function statCard(label, value, detail, iconName, tone, trend) {
  return `<article class="stat-card">
    <div class="stat-top"><span class="stat-icon ${tone}">${icon(iconName)}</span><span class="trend ${trend.startsWith('+') ? 'up' : ''}">${trend}</span></div>
    <strong>${value}</strong><span class="stat-label">${label}</span><span class="stat-detail">${detail}</span>
  </article>`;
}

function connectionPill(label, connected = true) {
  return `<span class="connection-pill"><span class="status-dot ${connected ? 'live' : ''}"></span>${label}</span>`;
}

function renderShell(content) {
  app.innerHTML = `<div class="app-shell ${state.mobileNav ? 'nav-open' : ''}">
    <aside class="sidebar">
      <div class="brand"><span class="brand-orbit"><i></i><b></b></span><span>orbit</span><em>beta</em></div>
      <div class="workspace-switcher"><span class="avatar avatar-mint">MM</span><span><b>Mikdad's workspace</b><small>Personal workspace</small></span>${icon('chevron')}</div>
      <nav class="primary-nav" aria-label="Main navigation">
        <span class="nav-label">Workspace</span>
        ${navItems.map(([id, label, iconName]) => `<button class="nav-item ${state.activeNav === id ? 'active' : ''}" data-nav="${id}">${icon(iconName)}<span>${label}</span>${id === 'jobs' ? '<b class="nav-count">4</b>' : ''}</button>`).join('')}
        <span class="nav-label second">Account</span>
        <button class="nav-item ${state.activeNav === 'settings' ? 'active' : ''}" data-nav="settings">${icon('settings')}<span>Settings</span></button>
      </nav>
      <div class="sidebar-bottom">
        <div class="connector-card"><div class="connector-heading"><span class="plug-dot">${icon('link')}</span><span><b>Browser connector</b><small>Ready to capture jobs</small></span><span class="status-dot live"></span></div><button data-action="connector">Manage connections ${icon('arrow')}</button></div>
        <div class="user-card"><span class="avatar avatar-coral">MM</span><span><b>Muhammed Mikdad</b><small>Free plan</small></span>${icon('chevron')}</div>
      </div>
    </aside>
    <div class="mobile-backdrop" data-action="close-nav"></div>
    <main class="main-content">
      <header class="topbar"><button class="mobile-menu" data-action="toggle-nav">${icon('menu')}</button><div class="breadcrumbs"><span>Workspace</span><b>/</b><strong>${state.activeNav === 'overview' ? 'Overview' : navItems.find((item) => item[0] === state.activeNav)?.[1] || 'Settings'}</strong></div><div class="topbar-actions"><div class="global-search">${icon('search')}<input aria-label="Search" placeholder="Search jobs, activity..." /><kbd>⌘ K</kbd></div><button class="icon-button notification" aria-label="Notifications">${icon('bell')}<i></i></button><span class="top-avatar">MM</span></div></header>
      <div class="page-content">${content}</div>
    </main>
    ${state.modal ? modalTemplate() : ''}
    ${state.selectedJob ? jobDrawer() : ''}
    ${state.toast ? `<div class="toast">${icon('check')}<span>${escapeHtml(state.toast)}</span></div>` : ''}
  </div>`;
  bindEvents();
}

function pageHeader(eyebrow, title, subtitle, action = '') {
  return `<div class="page-header"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="page-subtitle">${subtitle}</p></div>${action}</div>`;
}

function overviewPage() {
  const readyCount = state.jobs.filter((job) => job.status === 'Resume ready').length;
  return `<section class="welcome-row"><div><p class="eyebrow">Monday, August 31, 2026</p><h1>Good morning, Mikdad <span class="wave">✦</span></h1><p class="page-subtitle">Your next great opportunity is closer than you think.</p></div><button class="button button-dark" data-action="new-application">${icon('plus')} Add job manually</button></section>
    <section class="hero-card">
      <div class="hero-copy"><div class="hero-kicker"><span class="pulse"></span> Agent is standing by</div><h2>Make every application<br /><em>feel personal.</em></h2><p>Orbit finds your best-fit roles, tunes your resume to each one, and gets everything ready for your review.</p><div class="hero-actions"><button class="button button-light" data-action="sync">${icon('link')} Sync Indeed jobs</button><button class="text-button light" data-action="how-it-works">See how it works ${icon('arrow')}</button></div></div>
      <div class="hero-visual" aria-label="Application workflow illustration"><div class="orbit-lines"></div><div class="hero-orbit-center"><span class="brand-orbit large"><i></i><b></b></span><span>orbit</span></div><div class="float-card float-card-one"><span class="mini-logo blue">NS</span><span><b>Nexa Systems</b><small>94% match</small></span><span class="mini-check">${icon('check')}</span></div><div class="float-card float-card-two"><span class="doc-icon">${icon('file')}</span><span><b>Resume v3.pdf</b><small>ATS ready</small></span></div><span class="sparkle sparkle-a">✦</span><span class="sparkle sparkle-b">✧</span></div>
    </section>
    <div class="stats-grid">${statCard('New matches', '06', 'Since your last sync', 'briefcase', 'blue', '+ 2 today')}${statCard('Ready for review', String(readyCount + 2).padStart(2, '0'), 'Nothing sends without you', 'file', 'lavender', '+ 1 today')}${statCard('Applications this week', '08', '3 more than last week', 'activity', 'orange', '+ 60%')}${statCard('Average match score', '88%', 'Across your active queue', 'sparkle', 'mint', '+ 4%')}</div>
    <div class="section-grid"><section class="panel queue-panel"><div class="panel-heading"><div><p class="eyebrow">Your shortlist</p><h2>Priority job queue</h2></div><button class="link-button" data-nav="jobs">View all ${icon('arrow')}</button></div><div class="filter-tabs"><button class="${state.filter === 'All' ? 'active' : ''}" data-filter="All">All <b>4</b></button><button class="${state.filter === 'Ready' ? 'active' : ''}" data-filter="Ready">Ready <b>2</b></button><button class="${state.filter === 'Needs review' ? 'active' : ''}" data-filter="Needs review">Needs review <b>2</b></button></div><div class="job-list">${state.jobs.slice(0, 3).map(jobRow).join('')}</div></section><aside class="panel workflow-panel"><div class="panel-heading"><div><p class="eyebrow">Always in control</p><h2>Application flow</h2></div><span class="safe-badge">${icon('shield')} Safe mode</span></div><div class="flow-list"><div class="flow-item done"><span class="flow-number">${icon('check')}</span><span><b>Find a role</b><small>Orbit watches your connected searches</small></span></div><div class="flow-item done"><span class="flow-number">${icon('check')}</span><span><b>Understand the brief</b><small>Skills and signals are extracted</small></span></div><div class="flow-item active"><span class="flow-number">3</span><span><b>Tailor your resume</b><small>One clear version for each role</small></span></div><div class="flow-item"><span class="flow-number">4</span><span><b>You review &amp; approve</b><small>Nothing submits without you</small></span></div></div><div class="workflow-note">${icon('info')} <span>Orbit prepares applications. <b>You stay in the loop</b> before any upload or submission.</span></div></aside></div>
    <section class="panel activity-panel"><div class="panel-heading"><div><p class="eyebrow">Your workspace, at a glance</p><h2>Recent activity</h2></div><button class="link-button" data-nav="activity">See all activity ${icon('arrow')}</button></div><div class="activity-list">${state.activity.slice(0, 3).map(activityRow).join('')}</div></section>`;
}

function activityRow(item) {
  return `<div class="activity-row"><span class="activity-icon ${item.tone}">${icon(item.icon)}</span><span class="activity-copy"><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.detail)}</small></span><time>${escapeHtml(item.time)}</time></div>`;
}

function jobsPage() {
  const filtered = state.jobs.filter((job) => state.filter === 'All' || (state.filter === 'Ready' ? job.workflow >= 3 : job.workflow < 3));
  return `${pageHeader('Job queue', 'Roles worth your time', 'Fresh opportunities from your connected sources, ranked by fit.', `<button class="button button-dark" data-action="sync">${icon('link')} Sync sources</button>`)}<section class="queue-toolbar"><div class="queue-summary"><b>${filtered.length} roles</b><span>updated just now</span></div><div class="filter-tabs"><button class="${state.filter === 'All' ? 'active' : ''}" data-filter="All">All <b>4</b></button><button class="${state.filter === 'Ready' ? 'active' : ''}" data-filter="Ready">Ready <b>2</b></button><button class="${state.filter === 'Needs review' ? 'active' : ''}" data-filter="Needs review">Needs review <b>2</b></button></div><button class="sort-button">Best match ${icon('chevron')}</button></section><section class="full-job-list">${filtered.map((job) => `<button class="full-job-card" data-job="${job.id}"><div class="job-card-top">${companyMark(job)}<span class="job-source">${escapeHtml(job.source)} ${icon('external')}</span></div><h3>${escapeHtml(job.title)}</h3><p class="company-line">${escapeHtml(job.company)} <i>·</i> ${escapeHtml(job.location)}</p><div class="job-card-bottom"><div class="tag-list">${job.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join('')}</div><span class="job-status ${statusClass(job.status)}">${job.status}</span>${scoreRing(job.score, true)}</div></button>`).join('')}</section>`;
}

function resumePage() {
  return `${pageHeader('Resume studio', 'Your resume, made relevant', 'A clean master resume plus tailored versions for the roles you care about.', `<button class="button button-dark" data-action="new-application">${icon('plus')} Tailor for a job</button>`)}<section class="resume-hero panel"><div class="resume-hero-copy"><span class="resume-file-badge">${icon('file')}</span><div><p class="eyebrow">Master resume</p><h2>Muhammed Mikdad Um</h2><p>Full-Stack Software Engineer · B.Tech CSE · Available immediately</p><div class="resume-meta"><span>${icon('check')} ATS-friendly</span><span>${icon('clock')} Updated 2 days ago</span></div></div></div><button class="button button-outline" data-action="preview-master">Preview resume ${icon('external')}</button></section><div class="resume-grid"><section class="panel versions-panel"><div class="panel-heading"><div><p class="eyebrow">Tailored versions</p><h2>Resume library</h2></div><span class="count-badge">3 versions</span></div><div class="version-list">${state.jobs.filter((job) => job.workflow >= 3).map((job, index) => `<div class="version-row"><span class="version-icon ${job.color}">${icon('file')}</span><span><b>${escapeHtml(job.title)}</b><small>${escapeHtml(job.company)} · Resume v${3 - index} · ${job.score}% match</small></span><span class="version-ready">${icon('check')} Ready</span><button class="kebab" data-job="${job.id}">•••</button></div>`).join('')}</div></section><aside class="panel resume-tips"><div class="tip-art">✦</div><p class="eyebrow">Orbit's approach</p><h2>Specific beats generic.</h2><p>Each version keeps your real experience intact while bringing the most relevant evidence to the top.</p><div class="tip-rule"></div><div class="tip-stat"><b>100%</b><span>human-reviewed<br />before sending</span></div></aside></div>`;
}

function activityPage() {
  return `${pageHeader('Activity', 'A clear trail of progress', 'Every capture, edit, and preparation step in one place.', `<button class="button button-outline" data-action="export-log">${icon('download')} Export log</button>`)}<section class="panel activity-full"><div class="activity-filter"><div class="date-range">Last 30 days ${icon('chevron')}</div><span class="activity-total">18 events</span></div>${state.activity.concat([{ icon: 'check', tone: 'mint', title: 'Resume master updated', detail: 'Added TrueLedge project details', time: 'Aug 29, 2026' }, { icon: 'shield', tone: 'lavender', title: 'Safe mode enabled', detail: 'Manual approval is required before submit', time: 'Aug 28, 2026' }]).map(activityRow).join('')}</section>`;
}

function settingsPage() {
  return `${pageHeader('Settings', 'Make Orbit work your way', 'Connections, preferences, and guardrails for your workflow.', '')}<div class="settings-grid"><section class="panel settings-panel"><div class="panel-heading"><div><p class="eyebrow">Connected sources</p><h2>Browser connections</h2></div><button class="link-button" data-action="connector">Manage ${icon('arrow')}</button></div><div class="setting-row"><span class="setting-brand indeed-mark">in</span><span><b>Indeed</b><small>Signed in · Last synced 4 min ago</small></span><span class="connected-label"><i></i> Connected</span></div><div class="setting-row"><span class="setting-brand arena-mark">✦</span><span><b>Arena.ai</b><small>Prompt handoff is ready</small></span><span class="connected-label"><i></i> Connected</span></div><div class="setting-row"><span class="setting-brand web-mark">↗</span><span><b>Company websites</b><small>Upload helper activates on review</small></span><span class="connected-label muted-label">On demand</span></div></section><section class="panel settings-panel"><div class="panel-heading"><div><p class="eyebrow">Guardrails</p><h2>Safe mode</h2></div><button class="toggle ${state.safeMode ? 'on' : ''}" data-action="toggle-safe" aria-label="Toggle safe mode"><i></i></button></div><p class="settings-description">Orbit can gather, tailor, and prepare. You always approve the final upload or submission.</p><div class="guardrail-list"><div>${icon('check')} Never submits automatically</div><div>${icon('check')} Shows exactly what changes</div><div>${icon('check')} Keeps your source resume untouched</div></div></section></div><section class="panel profile-panel"><div class="profile-heading"><span class="avatar avatar-coral large-avatar">MM</span><div><p class="eyebrow">Your profile</p><h2>Muhammed Mikdad Um</h2><p>Abu Dhabi, UAE · Immediate availability</p></div><button class="button button-outline">Edit profile</button></div><div class="profile-fields"><div><span>Target locations</span><b>Abu Dhabi, Dubai · Remote UAE</b></div><div><span>Role focus</span><b>Full-Stack · Frontend · AI Product</b></div><div><span>Master resume</span><b>muhammed-mikdad-resume.html</b></div></div></section>`;
}

function renderPage() {
  if (state.activeNav === 'jobs') return jobsPage();
  if (state.activeNav === 'resume') return resumePage();
  if (state.activeNav === 'activity') return activityPage();
  if (state.activeNav === 'settings') return settingsPage();
  return overviewPage();
}

function jobDrawer() {
  const job = state.jobs.find((item) => item.id === state.selectedJob);
  if (!job) return '';
  const isReady = job.workflow >= 3;
  const isGenerating = state.generating && state.selectedJob === job.id;
  return `<div class="drawer-backdrop" data-action="close-job"></div><aside class="job-drawer"><div class="drawer-header"><span class="eyebrow">Job details</span><button class="icon-button" data-action="close-job" aria-label="Close details">${icon('close')}</button></div><div class="drawer-job-heading">${companyMark(job)}<div><h2>${escapeHtml(job.title)}</h2><p>${escapeHtml(job.company)} <i>·</i> ${escapeHtml(job.location)}</p></div></div><div class="drawer-score"><div><span class="eyebrow">Orbit match</span><strong>${job.score}%</strong><small>Strong fit for your profile</small></div>${scoreRing(job.score)}</div><div class="drawer-actions">${isGenerating ? `<button class="button button-dark is-loading" disabled><span class="spinner"></span> Tailoring your resume...</button>` : isReady ? `<button class="button button-dark" data-action="prepare-upload">${icon('upload')} Review application</button>` : `<button class="button button-dark" data-action="tailor">${icon('sparkle')} Tailor my resume</button>`}<button class="button button-outline" data-action="open-source">${icon('external')} Open source job</button></div><button class="drawer-handoff" data-action="handoff">${icon('sparkle')} Send the brief to your open Arena.ai session ${icon('arrow')}</button><div class="drawer-section"><p class="eyebrow">Why it fits</p><div class="insight-list">${job.highlights.map((item) => `<span>${icon('check')} ${escapeHtml(item)}</span>`).join('')}</div></div><div class="drawer-section description-section"><p class="eyebrow">Full job description</p><p>${escapeHtml(job.description)}</p></div><div class="drawer-section"><p class="eyebrow">Application flow</p><div class="mini-flow">${['Captured', 'Analyzed', 'Tailored', 'Ready'].map((item, index) => `<span class="${job.workflow >= index ? 'done' : ''}"><i>${job.workflow >= index ? icon('check') : index + 1}</i>${item}</span>`).join('')}</div></div><div class="drawer-footer">${icon('shield')} Safe mode is on — nothing is sent without your approval.</div></aside>`;
}

function modalTemplate() {
  if (state.modal === 'capture') return `<div class="modal-backdrop" data-action="close-modal"><section class="modal capture-modal" data-modal-content><button class="modal-close" data-action="close-modal">${icon('close')}</button><div class="modal-icon mint-icon">${icon('plus')}</div><p class="eyebrow">Add a role</p><h2>Bring a job into Orbit</h2><p class="modal-lead">Paste the full job description from Indeed or a company site. Orbit will extract the role, score the fit, and queue it for your review.</p><label for="job-description">Full job description</label><textarea id="job-description" placeholder="Paste the job description here...">${escapeHtml(state.draftDescription || '')}</textarea><div class="modal-hint">${icon('shield')} Your job description stays in this workspace.</div><div class="modal-actions"><button class="button button-outline" data-action="close-modal">Cancel</button><button class="button button-dark" data-action="analyze">Analyze role ${icon('arrow')}</button></div></section></div>`;
  if (state.modal === 'connector') return `<div class="modal-backdrop" data-action="close-modal"><section class="modal connector-modal" data-modal-content><button class="modal-close" data-action="close-modal">${icon('close')}</button><div class="modal-icon blue-icon">${icon('link')}</div><p class="eyebrow">Browser connector</p><h2>Your tabs, working together.</h2><p class="modal-lead">Orbit connects to tabs you already have open. It never asks for or stores your passwords.</p><div class="connection-steps"><div class="connection-step connected"><span>1</span><div><b>Indeed</b><small>Signed in tab detected · ready to capture</small></div><i>${icon('check')}</i></div><div class="connection-step connected"><span>2</span><div><b>Arena.ai</b><small>Open session detected · ready for handoff</small></div><i>${icon('check')}</i></div><div class="connection-step"><span>3</span><div><b>Application site</b><small>Orbit will help fill the upload step after review</small></div><i>${icon('clock')}</i></div></div><div class="connector-note">${icon('info')} Open Indeed and Arena.ai in this browser, then click <b>Sync sources</b> to refresh.</div><div class="modal-actions"><button class="button button-dark" data-action="sync">Sync sources ${icon('arrow')}</button></div></section></div>`;
  if (state.modal === 'handoff') { const job = state.jobs.find((item) => item.id === state.selectedJob); return `<div class="modal-backdrop" data-action="close-modal"><section class="modal handoff-modal" data-modal-content><button class="modal-close" data-action="close-modal">${icon('close')}</button><div class="modal-icon lavender-icon">${icon('sparkle')}</div><p class="eyebrow">Arena.ai handoff</p><h2>${state.handoffInserted ? 'Brief inserted into Arena.ai.' : 'Your brief is ready to go.'}</h2><p class="modal-lead">${state.handoffInserted ? 'The Arena.ai composer is focused with your prompt. Review it, then send it yourself when ready.' : `Orbit will try the open Arena.ai session first. If the connector is unavailable, open Arena.ai and paste the copied brief into the composer.`}</p><label for="handoff-prompt">Prompt to send ${job ? `· ${escapeHtml(job.company)}` : ''}</label><textarea id="handoff-prompt" readonly>${escapeHtml(state.handoffPrompt)}</textarea><div class="modal-hint">${icon('shield')} The prompt includes only your supplied resume facts and this job description.</div><div class="handoff-buttons"><button class="button button-outline" data-action="copy-prompt">${icon('file')} Copy prompt</button><button class="button button-dark" data-action="open-arena">${icon('external')} Open Arena.ai</button></div><button class="finish-link" data-action="close-modal">Back to job details ${icon('arrow')}</button></section></div>`; }
  if (state.modal === 'approval') { const job = state.jobs.find((item) => item.id === state.selectedJob); return `<div class="modal-backdrop" data-action="close-modal"><section class="modal approval-modal" data-modal-content><button class="modal-close" data-action="close-modal">${icon('close')}</button><div class="modal-icon coral-icon">${icon('shield')}</div><p class="eyebrow">Your review</p><h2>Ready to prepare this application?</h2><p class="modal-lead">Orbit has tailored a resume for <b>${escapeHtml(job.company)}</b>. Look over the changes before opening the application page.</p><div class="approval-preview"><div>${companyMark(job, true)}<span><b>${escapeHtml(job.title)}</b><small>${escapeHtml(job.company)} · ${job.score}% match</small></span></div><span class="pdf-chip">${icon('file')} Resume v3.pdf</span></div><div class="review-checks"><span>${icon('check')} 6 relevant keywords surfaced</span><span>${icon('check')} No experience or dates invented</span><span>${icon('check')} ATS-friendly, single-column layout</span></div><div class="modal-actions"><button class="button button-outline" data-action="close-modal">Keep editing</button><button class="button button-dark" data-action="approve">Prepare upload ${icon('arrow')}</button></div></section></div>`; }
  if (state.modal === 'upload') { const job = state.jobs.find((item) => item.id === state.selectedJob); return `<div class="modal-backdrop" data-action="close-modal"><section class="modal upload-modal" data-modal-content><button class="modal-close" data-action="close-modal">${icon('close')}</button><div class="modal-icon mint-icon">${icon('check')}</div><p class="eyebrow">Application prepared</p><h2>One last step is yours.</h2><p class="modal-lead">Your ATS-friendly PDF is ready for <b>${escapeHtml(job.company)}</b>. Open the source page, then upload it yourself when every field looks right.</p><div class="upload-status"><span class="upload-check">${icon('check')}</span><div><b>Resume v3.pdf</b><small>Prepared just now · 94% keyword coverage</small></div><button class="icon-button" data-action="print" aria-label="Download resume">${icon('download')}</button></div><div class="manual-note">${icon('shield')} <span>Orbit will not click Submit. Check every field, upload the PDF, and send only when it looks right.</span></div><div class="modal-actions"><button class="button button-outline" data-action="open-source">${icon('external')} Open source page</button><button class="button button-dark" data-action="print">${icon('download')} Print / save PDF</button></div><button class="finish-link" data-action="finish">Mark as reviewed ${icon('check')}</button></section></div>`; }
  return '';
}

function bindEvents() {
  document.querySelectorAll('[data-nav]').forEach((element) => element.addEventListener('click', () => {
    state.activeNav = element.dataset.nav;
    state.selectedJob = null;
    state.mobileNav = false;
    render();
  }));
  document.querySelectorAll('[data-job]').forEach((element) => element.addEventListener('click', () => {
    state.selectedJob = element.dataset.job;
    render();
  }));
  document.querySelectorAll('[data-filter]').forEach((element) => element.addEventListener('click', () => {
    state.filter = element.dataset.filter;
    render();
  }));
  document.querySelectorAll('[data-action]').forEach((element) => element.addEventListener('click', (event) => {
    const action = element.dataset.action;
    if (action === 'close-modal' && event.target !== element && element.classList.contains('modal-backdrop')) return;
    handleAction(action);
  }));
  const textarea = document.querySelector('#job-description');
  if (textarea) textarea.addEventListener('input', () => { state.draftDescription = textarea.value; });
}

function handleAction(action) {
  if (action === 'toggle-nav') { state.mobileNav = !state.mobileNav; render(); return; }
  if (action === 'close-nav') { state.mobileNav = false; render(); return; }
  if (action === 'new-application') { state.modal = 'capture'; render(); return; }
  if (action === 'connector') { state.modal = 'connector'; render(); return; }
  if (action === 'close-modal') { state.modal = null; render(); return; }
  if (action === 'close-job') { state.selectedJob = null; render(); return; }
  if (action === 'how-it-works') { state.modal = 'connector'; render(); return; }
  if (action === 'sync') {
    state.modal = null;
    window.postMessage({ source: 'orbit-app', type: 'orbit:sync' }, '*');
    state.toast = 'Checking your open Indeed tab…';
    render();
    setTimeout(() => { if (state.toast === 'Checking your open Indeed tab…') { state.toast = 'Sources synced — 2 new roles added to your queue'; render(); } }, 1800);
    setTimeout(() => { state.toast = null; render(); }, 4000);
    return;
  }
  if (action === 'handoff') {
    const job = state.jobs.find((item) => item.id === state.selectedJob);
    if (!job) return;
    state.handoffPrompt = buildArenaPrompt(job);
    state.handoffPending = true;
    state.handoffInserted = false;
    state.modal = 'handoff';
    window.postMessage({ source: 'orbit-app', type: 'orbit:handoff', prompt: state.handoffPrompt }, '*');
    // Clipboard is the reliable fallback when the extension is not installed or the
    // Arena composer is still loading. The call is initiated by the user's click.
    copyPrompt().catch(() => {});
    render();
    setTimeout(() => {
      if (state.handoffPending) {
        state.handoffPending = false;
        state.toast = 'Prompt copied — open Arena.ai and paste it into the composer';
        render();
        setTimeout(() => { state.toast = null; render(); }, 3200);
      }
    }, 1800);
    return;
  }
  if (action === 'copy-prompt') {
    copyPrompt().then(() => {
      state.toast = 'Prompt copied to clipboard';
      render();
      setTimeout(() => { state.toast = null; render(); }, 2500);
    }).catch(() => {
      state.toast = 'Select the prompt text and copy it manually';
      render();
      setTimeout(() => { state.toast = null; render(); }, 2500);
    });
    return;
  }
  if (action === 'open-arena') {
    window.open('https://arena.ai/agent', '_blank', 'noopener');
    state.toast = 'Arena.ai opened — paste the copied prompt into the composer';
    render();
    setTimeout(() => { state.toast = null; render(); }, 3200);
    return;
  }
  if (action === 'analyze') {
    const description = document.querySelector('#job-description')?.value.trim() || '';
    if (!description) { state.toast = 'Paste a job description first'; render(); setTimeout(() => { state.toast = null; render(); }, 2500); return; }
    const newJob = { id: `pasted-${Date.now()}`, company: 'New employer', initials: 'NE', color: 'coral', title: 'Software Engineer', location: 'Location from description', posted: 'just now', source: 'Pasted brief', score: 84, status: 'Needs review', tags: ['Role brief', 'New match'], description, highlights: ['Relevant experience identified', 'Skills ready to compare', 'Human review recommended'], workflow: 1 };
    state.jobs.unshift(newJob); state.selectedJob = newJob.id; state.modal = null; state.draftDescription = ''; state.toast = 'Role analyzed and added to your queue'; render(); setTimeout(() => { state.toast = null; render(); }, 3000); return;
  }
  if (action === 'tailor') {
    state.generating = true; render();
    setTimeout(() => {
      const job = state.jobs.find((item) => item.id === state.selectedJob);
      if (job) { job.workflow = 3; job.status = 'Resume ready'; }
      state.generating = false;
      state.toast = 'Tailored resume ready for your review';
      render();
      setTimeout(() => { state.toast = null; render(); }, 3200);
    }, 1350);
    return;
  }
  if (action === 'prepare-upload') { state.modal = 'approval'; render(); return; }
  if (action === 'approve') {
    const job = state.jobs.find((item) => item.id === state.selectedJob);
    if (job) { job.status = 'Prepared'; job.workflow = 4; }
    state.modal = 'upload';
    state.activity.unshift({ icon: 'check', tone: 'mint', title: `Application prepared for ${job?.company || 'role'}`, detail: 'Resume v3.pdf · awaiting your upload', time: 'Just now' });
    render();
    return;
  }
  if (action === 'finish') { state.modal = null; state.selectedJob = null; state.toast = 'Nice work — application marked complete'; render(); setTimeout(() => { state.toast = null; render(); }, 3000); return; }
  if (action === 'print' || action === 'preview-master') { printResume(state.jobs.find((item) => item.id === state.selectedJob)); return; }
  if (action === 'open-source') { const job = state.jobs.find((item) => item.id === state.selectedJob); if (job?.url) window.open(job.url, '_blank', 'noopener'); else window.open('https://www.indeed.com/', '_blank', 'noopener'); state.toast = 'Opening the source job in a new tab'; render(); setTimeout(() => { state.toast = null; render(); }, 2500); return; }
  if (action === 'toggle-safe') { state.safeMode = !state.safeMode; state.toast = state.safeMode ? 'Safe mode enabled' : 'Safe mode cannot be disabled for submissions'; state.safeMode = true; render(); setTimeout(() => { state.toast = null; render(); }, 2500); return; }
  if (action === 'export-log') { downloadText('orbit-activity-log.txt', state.activity.map((item) => `${item.time} — ${item.title} — ${item.detail}`).join('\n')); state.toast = 'Activity log downloaded'; render(); setTimeout(() => { state.toast = null; render(); }, 2500); }
}

function buildArenaPrompt(job) {
  const reference = resumeHtml();
  return `You are tailoring a resume for a real job application. Use only the candidate facts below; do not invent experience, dates, metrics, tools, or qualifications. Tailor the wording and ordering to the job, but preserve the exact ATS-friendly HTML structure and CSS conventions in the reference. Return ONLY one complete HTML document beginning with <!doctype html> and ending with </html>. Do not wrap it in markdown fences. Do not add notes, commentary, explanations, or a cover letter.

CANDIDATE RESUME FACTS:
Muhammed Mikdad Um — Abu Dhabi, UAE — Full-Stack Software Engineer — B.Tech Computer Science, 2026. Next.js, React, TypeScript, JavaScript, HTML, CSS, Tailwind, Node.js, Express, REST APIs, Supabase, PostgreSQL, SQL, Auth, RBAC, Webhooks, AWS ECS/App Runner, Docker, CI/CD, Gemini Vision API, prompt engineering, Text-to-SQL guardrails, Flutter, Python, Tableau, Power BI.

EXPERIENCE:
Jsquare (Client: Astra Gold & Diamonds), Full-Stack Developer and Team Lead, Jan 2025–Mar 2026: scaled a Next.js and Supabase platform from 45,000 to 79,000+ active users; built referral and commission automation and payment workflows with idempotent webhooks; shipped an offline-first Flutter app and coordinated a small engineering team. Trainity, Data Analyst Intern, Sep–Dec 2024: delivered BI reporting with Python, SQL, Tableau, and Power BI; ranked Top 7 of 1,000+ candidates in the program.

PROJECTS:
TrueLedge AI accounting and audit SaaS: Gemini Vision invoice extraction, human-in-the-loop workflows, deterministic SQL bank matching with LLM fallback, secure Text-to-SQL over restricted read-only views. Algorithmic Trading and Backtesting Engine: Python workflow, WebSocket market data, risk controls. E-commerce platforms: Next.js apps with JWT authentication, RBAC admin flows, and sales dashboards.

JOB DESCRIPTION:
${job.description}

REQUIRED HTML REFERENCE — preserve this document structure and ATS-friendly single-column styling. Replace only the resume copy needed to truthfully tailor it to the job:

${reference}

Final check: output only the complete HTML document. No notes.`;
}

function resumeHtml(job) {
  const focus = job ? `Availability: Immediate | Open to Abu Dhabi / Dubai | Target role: ${job.title} at ${job.company}` : 'Availability: Immediate | Open to Abu Dhabi / Dubai | Seeking visa sponsorship';
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MUHAMMED MIKDAD UM - Resume</title>
  <style>
    /* ATS-friendly: single column, no tables, no icons/images, minimal styling */
    :root { --text: #111; --muted: #444; --rule: #d0d0d0; }

    html, body { background: #fff; }
    body {
      margin: 0;
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      font-size: 11pt;
      line-height: 1.35;
    }

    .page {
      max-width: 8.5in;
      margin: 0 auto;
      padding: 0.6in;
    }

    h1 {
      font-size: 18pt;
      margin: 0 0 6px 0;
      letter-spacing: 0.2px;
    }

    .contact {
      margin: 0 0 10px 0;
      color: var(--muted);
    }
    .contact a { color: inherit; text-decoration: none; }

    .meta {
      margin: 0 0 14px 0;
      color: var(--muted);
    }

    h2 {
      font-size: 12pt;
      margin: 14px 0 6px 0;
      padding-top: 8px;
      border-top: 1px solid var(--rule);
      text-transform: uppercase;
      letter-spacing: 0.6px;
    }

    h3 {
      font-size: 11pt;
      margin: 10px 0 2px 0;
    }

    .roleline {
      margin: 0 0 6px 0;
      color: var(--muted);
    }

    p { margin: 6px 0; }
    ul { margin: 6px 0 8px 18px; padding: 0; }
    li { margin: 3px 0; }

    .label { font-weight: 700; }
    .small { color: var(--muted); }

    @media print {
      /* Ensure clean print */
      .page { padding: 0.5in; }
      a { text-decoration: none; color: #000; }
      h2 { page-break-after: avoid; }
      ul, p { page-break-inside: avoid; }
      @page { size: A4; margin: 0.5in; }
    }
  </style>
</head>

<body>
  <main class="page">
    <header>
      <h1>MUHAMMED MIKDAD UM</h1>
      <p class="contact">
        Abu Dhabi, UAE |
        Phone: +971 52 624 5540 |
        Email: <a href="mailto:mikplax@gmail.com">mikplax@gmail.com</a><br />
        LinkedIn: <a href="https://linkedin.com/in/mikdaaad">linkedin.com/in/mikdaaad</a> |
        Portfolio: <a href="https://mikdad.somberonyx.in">mikdad.somberonyx.in</a>
      </p>
      <p class="meta">
        ${escapeHtml(focus)}
      </p>
    </header>

    <section aria-label="Summary">
      <h2>Summary</h2>
      <p>
        Full-Stack Software Engineer (B.Tech CSE, 2026) with hands-on experience shipping Next.js + TypeScript SaaS,
        Supabase/PostgreSQL, and AWS deployments. Built an AI-enabled accounting/audit product with Gemini Vision
        document extraction, LLM-assisted reconciliation, and secure Text-to-SQL. Scaled a production platform to
        79,000+ active users and delivered a Flutter companion app. Immediate joiner.
      </p>
    </section>

    <section aria-label="Technical Skills">
      <h2>Technical Skills</h2>
      <p><span class="label">Frontend:</span> Next.js, React, TypeScript, JavaScript (ES6+), HTML, CSS, Tailwind CSS</p>
      <p><span class="label">Backend:</span> Node.js, Express.js, REST APIs, Supabase, PostgreSQL, SQL, Auth, RBAC, Webhooks</p>
      <p><span class="label">Cloud/DevOps:</span> AWS (ECS, App Runner), Docker, CI/CD (Git-based), AWS Amplify</p>
      <p><span class="label">AI / LLM:</span> Gemini Vision API, prompt engineering (few-shot), guardrails for Text-to-SQL, human-in-the-loop workflows</p>
      <p><span class="label">Mobile:</span> Flutter, React Native</p>
      <p><span class="label">Analytics:</span> Python, Tableau, Power BI</p>
    </section>

    <section aria-label="Experience">
      <h2>Experience</h2>

      <h3>Jsquare (Client: Astra Gold &amp; Diamonds) — Full-Stack Developer &amp; Team Lead</h3>
      <p class="roleline">Remote (Mangalore, India) | Jan 2025 – Mar 2026</p>
      <ul>
        <li>
          Scaled a Next.js + Supabase production platform from 45,000 to 79,000+ active users using optimized Postgres
          design, RLS policies, triggers, and serverless functions.
        </li>
        <li>
          Built referral/commission automation and integrated payment workflows with idempotent webhook handling
          (Razorpay, PhonePe).
        </li>
        <li>
          Shipped a Flutter mobile app (offline-first) and coordinated delivery with a small engineering team
          (planning, reviews, releases).
        </li>
      </ul>

      <h3>Trainity — Data Analyst Intern</h3>
      <p class="roleline">Virtual (Bangalore, India) | Sep 2024 – Dec 2024</p>
      <ul>
        <li>
          Delivered BI reporting using Python, SQL, Tableau/Power BI; ranked Top 7 of 1,000+ candidates in the program
          (as awarded by the program).
        </li>
      </ul>
    </section>

    <section aria-label="Projects">
      <h2>Projects</h2>

      <h3>TrueLedge — AI-Enabled Accounting &amp; Audit SaaS | 2026</h3>
      <p class="small">Live demo: somberonyx.in</p>
      <ul>
        <li>
          Built a human-in-the-loop invoice ingestion pipeline using Gemini Vision to extract line items and draft
          accounting entries.
        </li>
        <li>
          Implemented a two-layer bank reconciliation approach: deterministic SQL matching + LLM fallback for
          semantic/ambiguous narrations.
        </li>
        <li>
          Developed a secure Text-to-SQL assistant over restricted read-only views to reduce SQL injection risk and
          prevent cross-tenant data exposure.
        </li>
        <li><span class="label">Tech:</span> Next.js, TypeScript, Supabase (PostgreSQL), Express, Tailwind, AWS</li>
      </ul>

      <h3>Algorithmic Trading &amp; Backtesting Engine | 2026</h3>
      <ul>
        <li>
          Built a Python-based backtesting + live execution workflow with WebSocket market data ingestion and risk
          controls (dynamic stop-loss).
        </li>
        <li><span class="label">Tech:</span> Python, WebSockets, Next.js</li>
      </ul>

      <h3>E-Commerce Platforms (ahdaldoors.in, Terrific.fit) | Jan 2025 – Feb 2025</h3>
      <ul>
        <li>
          Built Next.js e-commerce apps with JWT authentication, RBAC admin flows, and sales dashboarding.
        </li>
        <li><span class="label">Tech:</span> Next.js, JWT, RBAC, Payments</li>
      </ul>
    </section>

    <section aria-label="Education">
      <h2>Education</h2>
      <p>
        <span class="label">B.Tech, Computer Science</span> — Srinivas Institute of Technology (SIT), Mangalore | 2022 – 2026
      </p>
    </section>

    <section aria-label="Certifications">
      <h2>Certifications</h2>
      <ul>
        <li>Machine Learning Specialization — Stanford / DeepLearning.AI</li>
        <li>Full Stack Web Development Bootcamp — Udemy</li>
      </ul>
    </section>

    <section aria-label="Languages">
      <h2>Languages</h2>
      <p>English (Fluent) | Malayalam (Native) | Hindi (Fluent) | Kannada (Native)</p>
    </section>
  </main>
</body>
</html>`;
}

function printResume(job) {
  const popup = window.open('', '_blank', 'width=900,height=1000');
  if (!popup) { state.toast = 'Allow pop-ups to print your resume'; render(); return; }
  popup.document.open(); popup.document.write(resumeHtml(job)); popup.document.close();
}

function copyPrompt() {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(state.handoffPrompt);
  return Promise.reject(new Error('Clipboard is unavailable in this browser context.'));
}

function downloadText(name, contents) {
  const blob = new Blob([contents], { type: 'text/plain' });
  const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url);
}

window.addEventListener('message', (event) => {
  if (event.source !== window || event.data?.source !== 'orbit-extension') return;
  if (!event.data.ok) {
    state.handoffPending = false;
    state.toast = event.data.error || 'The browser connector needs attention';
    render();
    setTimeout(() => { state.toast = null; render(); }, 3200);
    return;
  }
  if (event.data.type === 'orbit:job-captured' && event.data.job) {
    const captured = event.data.job;
    const capturedJob = { id: `captured-${Date.now()}`, company: captured.company, initials: captured.company.split(/\\s+/).map((word) => word[0]).join('').slice(0, 2).toUpperCase(), color: 'blue', title: captured.title, location: captured.location, posted: 'just now', source: 'Indeed', score: 88, status: 'Needs review', tags: ['Captured', 'New role'], description: captured.description, highlights: ['Description captured in full', 'Skills ready to compare', 'Human review recommended'], workflow: 0, url: captured.url };
    state.jobs.unshift(capturedJob);
    state.activeNav = 'jobs';
    state.selectedJob = capturedJob.id;
    state.toast = 'Indeed role captured in full';
    render();
    setTimeout(() => { state.toast = null; render(); }, 3200);
  } else if (event.data.type === 'orbit:arena-ready') {
    state.handoffPending = false;
    state.handoffInserted = true;
    state.toast = 'Arena.ai is focused with your brief inserted';
    render();
    setTimeout(() => { state.toast = null; render(); }, 3200);
  }
});

function render() { renderShell(renderPage()); }
render();
