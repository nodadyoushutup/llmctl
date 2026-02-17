import { Link } from 'react-router-dom'

export default function SettingsInnerSidebar({
  title,
  ariaLabel,
  items,
  activeId,
  children,
}) {
  return (
    <section className="settings-inner-layout">
      <aside className="settings-inner-sidebar" aria-label={ariaLabel}>
        <p className="settings-inner-sidebar-title">{title}</p>
        <nav className="settings-inner-sidebar-nav">
          {items.map((item) => {
            const isActive = item.id === activeId
            return (
              <Link
                key={item.id}
                to={item.to}
                className={`settings-inner-sidebar-link${isActive ? ' is-active' : ''}`}
              >
                <span className="settings-inner-sidebar-link-main">
                  {item.icon ? <i className={item.icon} aria-hidden="true" /> : null}
                  <span>{item.label}</span>
                </span>
                <i className="fa-solid fa-chevron-right" aria-hidden="true" />
              </Link>
            )
          })}
        </nav>
      </aside>
      <section className="stack settings-inner-content">
        {children}
      </section>
    </section>
  )
}
