import { NavLink } from 'react-router-dom'
import { runtimeConfig, resolveSocketUrl } from '../config/runtime'

const navItems = [
  { to: '/migration', label: 'Migration Hub' },
  { to: '/overview', label: 'Legacy UI' },
  { to: '/parity-checklist', label: 'Parity Tracker' },
  { to: '/chat/activity', label: 'Chat Activity' },
  { to: '/execution-monitor', label: 'Execution Monitor' },
  { to: '/api-diagnostics', label: 'API Diagnostics' },
]

function navClassName({ isActive }) {
  return isActive ? 'top-nav-link top-nav-link-active' : 'top-nav-link'
}

export default function AppLayout({ children }) {
  return (
    <div className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">llmctl Studio</p>
          <h1>Frontend Migration Hub</h1>
        </div>
        <nav className="top-nav" aria-label="Primary">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navClassName}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="main-panel">{children}</main>

      <footer className="runtime-panel">
        <h2>Runtime wiring</h2>
        <ul>
          <li>
            <span>Web base</span>
            <code>{runtimeConfig.webBasePath}</code>
          </li>
          <li>
            <span>API base URL</span>
            <code>{runtimeConfig.apiBaseUrl || '(same origin)'}</code>
          </li>
          <li>
            <span>API base path</span>
            <code>{runtimeConfig.apiBasePath}</code>
          </li>
          <li>
            <span>Socket path</span>
            <code>{runtimeConfig.socketPath}</code>
          </li>
          <li>
            <span>Socket namespace</span>
            <code>{runtimeConfig.socketNamespace}</code>
          </li>
          <li>
            <span>Resolved socket URL</span>
            <code>{resolveSocketUrl()}</code>
          </li>
        </ul>
      </footer>
    </div>
  )
}
