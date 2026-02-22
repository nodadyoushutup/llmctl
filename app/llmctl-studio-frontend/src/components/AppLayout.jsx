import { useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

const navSections = [
  {
    id: 'agent',
    label: 'Agent',
    items: [
      { id: 'agents', to: '/agents', label: 'Agents', icon: 'fa-solid fa-robot' },
      { id: 'roles', to: '/roles', label: 'Roles', icon: 'fa-solid fa-scroll' },
      { id: 'skills', to: '/skills', label: 'Skills', icon: 'fa-solid fa-wand-magic-sparkles' },
    ],
  },
  {
    id: 'launch',
    label: 'Launch',
    items: [
      { id: 'chat', to: '/chat', label: 'Chat', icon: 'fa-solid fa-comments', matchPrefixes: ['/chat', '/chat/activity', '/chat/threads/'] },
      { id: 'flowcharts', to: '/flowcharts', label: 'Flowcharts', icon: 'fa-solid fa-diagram-project' },
      { id: 'quick', to: '/quick', label: 'Quick Node', icon: 'fa-solid fa-comment-dots' },
    ],
  },
  {
    id: 'workflow',
    label: 'Artifact',
    items: [
      {
        id: 'artifact-task',
        to: '/artifacts/type/task',
        label: 'Task',
        icon: 'fa-solid fa-list-check',
        matchPrefixes: ['/artifacts/type/task', '/artifacts/item/'],
      },
      { id: 'artifact-plan', to: '/artifacts/type/plan', label: 'Plan', icon: 'fa-solid fa-map' },
      { id: 'artifact-milestone', to: '/artifacts/type/milestone', label: 'Milestone', icon: 'fa-solid fa-flag-checkered' },
      { id: 'artifact-memory', to: '/artifacts/type/memory', label: 'Memory', icon: 'fa-solid fa-brain' },
      { id: 'artifact-decision', to: '/artifacts/type/decision', label: 'Decision', icon: 'fa-solid fa-code-branch' },
      { id: 'artifact-rag', to: '/artifacts/type/rag', label: 'RAG', icon: 'fa-solid fa-database' },
    ],
  },
  {
    id: 'activity',
    label: 'Activity',
    items: [
      { id: 'nodes', to: '/nodes', label: 'Nodes', icon: 'fa-solid fa-list-check' },
      { id: 'runs', to: '/runs', label: 'Autoruns', icon: 'fa-solid fa-bolt' },
      { id: 'execution-monitor', to: '/execution-monitor', label: 'Monitor', icon: 'fa-solid fa-wave-square' },
    ],
  },
  {
    id: 'rag',
    label: 'RAG',
    items: [
      { id: 'rag-sources', to: '/rag/sources', label: 'Sources', icon: 'fa-solid fa-database' },
    ],
  },
  {
    id: 'resources',
    label: 'Node Resources',
    items: [
      { id: 'mcps', to: '/mcps', label: 'MCP Servers', icon: 'fa-solid fa-network-wired' },
      { id: 'models', to: '/models', label: 'Models', icon: 'fa-solid fa-cubes' },
      { id: 'scripts', to: '/scripts', label: 'Scripts', icon: 'fa-solid fa-code' },
      { id: 'attachments', to: '/attachments', label: 'Attachments', icon: 'fa-solid fa-paperclip' },
    ],
  },
  {
    id: 'integration',
    label: 'Integration',
    items: [
      { id: 'github', to: '/github', label: 'GitHub', icon: 'fa-brands fa-github' },
      { id: 'jira', to: '/jira', label: 'Jira', icon: 'fa-brands fa-jira' },
      { id: 'confluence', to: '/confluence', label: 'Confluence', icon: 'fa-brands fa-confluence' },
      { id: 'chroma', to: '/chroma/collections', label: 'ChromaDB', icon: 'fa-solid fa-layer-group' },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    items: [
      { id: 'settings-provider', to: '/settings/provider', label: 'Providers', icon: 'fa-solid fa-wave-square' },
      { id: 'settings-runtime', to: '/settings/runtime', label: 'Runtime', icon: 'fa-solid fa-circle-info' },
      { id: 'settings-integrations', to: '/settings/integrations', label: 'Integrations', icon: 'fa-solid fa-plug' },
      { id: 'settings-chat', to: '/settings/chat', label: 'Chat', icon: 'fa-solid fa-comments' },
      { id: 'settings-core', to: '/settings/core', label: 'Core', icon: 'fa-solid fa-gear' },
    ],
  },
  {
    id: 'system',
    label: 'System',
    items: [
      { id: 'overview', to: '/overview', label: 'Overview', icon: 'fa-solid fa-gauge-high' },
      { id: 'parity', to: '/parity-checklist', label: 'Parity', icon: 'fa-solid fa-list-check' },
      { id: 'api-diagnostics', to: '/api-diagnostics', label: 'API', icon: 'fa-solid fa-heart-pulse' },
    ],
  },
]

function isItemActive(pathname, item) {
  const matches = item.matchPrefixes || [item.to, `${item.to}/`]
  return matches.some((prefix) => pathname === prefix || pathname.startsWith(prefix))
}

function findActive(pathname) {
  for (const section of navSections) {
    for (const item of section.items) {
      if (isItemActive(pathname, item)) {
        return { sectionId: section.id, item }
      }
    }
  }
  return null
}

function initialExpanded(pathname) {
  const active = findActive(pathname)
  const state = {}
  for (const section of navSections) {
    state[section.id] = active ? section.id === active.sectionId : section.id === 'agent'
  }
  return state
}

export default function AppLayout({ children }) {
  const location = useLocation()
  const active = useMemo(() => findActive(location.pathname), [location.pathname])
  const isFlowchartDetailRoute = useMemo(() => /^\/flowcharts\/\d+\/?$/.test(location.pathname), [location.pathname])
  const isNodeDetailRoute = useMemo(() => /^\/nodes\/\d+\/?$/.test(location.pathname), [location.pathname])
  const isChatRoute = useMemo(() => /^\/chat(?:\/|$)/.test(location.pathname), [location.pathname])
  const isFixedListRoute = useMemo(
    () => /^(\/nodes|\/runs|\/plans|\/milestones|\/memories|\/artifacts\/type\/[^/]+)\/?$/.test(location.pathname),
    [location.pathname],
  )
  const isFixedContentRoute = isFlowchartDetailRoute || isNodeDetailRoute || isFixedListRoute || isChatRoute
  const [expandedBySection, setExpandedBySection] = useState(() => initialExpanded(location.pathname))

  return (
    <div className="app-shell page">
      <div className="layout">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-icon">
              <i className="fa-solid fa-robot" />
            </div>
            <div>
              <p className="brand-title">LLMCTL</p>
            </div>
          </div>
          <nav className="nav" aria-label="Primary">
            {navSections.map((section, index) => {
              const expanded = section.id === active?.sectionId || Boolean(expandedBySection[section.id])
              return (
                <div key={section.id} className="nav-section" data-nav-section>
                  <button
                    className="nav-section-toggle"
                    type="button"
                    data-nav-section-toggle
                    aria-expanded={expanded ? 'true' : 'false'}
                    aria-controls={`nav-section-${index + 1}`}
                    onClick={() => setExpandedBySection((current) => ({ ...current, [section.id]: !expanded }))}
                  >
                    <span className="nav-section-title">{section.label}</span>
                    <i className="fa-solid fa-chevron-right nav-section-chevron" aria-hidden="true" />
                  </button>
                  <div
                    className="nav-section-items"
                    id={`nav-section-${index + 1}`}
                    data-nav-section-items
                    hidden={!expanded}
                  >
                    {section.items.map((item) => {
                      const itemIsActive = isItemActive(location.pathname, item)
                      return (
                        <Link key={item.id} to={item.to} className={`nav-item${itemIsActive ? ' is-active' : ''}`}>
                          <span className="row">
                            <span className="nav-icon">
                              <i className={item.icon} />
                            </span>
                            {item.label}
                          </span>
                          <i className="fa-solid fa-chevron-right" />
                        </Link>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </nav>
        </aside>

        <div className={`main${isFixedContentRoute ? ' main-is-fixed' : ''}`}>
          <main className={`content${isFixedContentRoute ? ' content-is-fixed' : ''}`}>{children}</main>
        </div>
      </div>
    </div>
  )
}
