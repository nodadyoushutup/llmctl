import { Link } from 'react-router-dom'
import PanelHeader from './PanelHeader'

function joinClassNames(...values) {
  return values.filter((value) => typeof value === 'string' && value.trim()).join(' ')
}

export default function TwoColumnListShell({
  ariaLabel,
  className = '',
  sidebarAriaLabel,
  sidebarTitle,
  sidebarItems,
  activeSidebarId,
  mainTitle,
  mainActions = null,
  children,
}) {
  const rootClassName = joinClassNames('column-list-page', className)

  return (
    <section className={rootClassName} aria-label={ariaLabel}>
      <section className="column-list-shell">
        <aside className="column-list-sidebar" aria-label={sidebarAriaLabel}>
          <PanelHeader title={sidebarTitle} className="column-list-sidebar-header" />
          <nav className="column-list-sidebar-nav">
            {sidebarItems.map((item) => {
              const isActive = item.id === activeSidebarId
              return (
                <Link
                  key={item.id}
                  to={item.to}
                  className={`column-list-sidebar-link${isActive ? ' is-active' : ''}`}
                >
                  <span className="column-list-sidebar-link-main">
                    {item.icon ? <i className={item.icon} aria-hidden="true" /> : null}
                    <span>{item.label}</span>
                  </span>
                  <i className="fa-solid fa-chevron-right" aria-hidden="true" />
                </Link>
              )
            })}
          </nav>
        </aside>

        <article className="card panel-card workflow-list-card column-list-main">
          <PanelHeader
            title={mainTitle}
            actions={mainActions}
            actionsClassName="workflow-list-panel-header-actions"
          />
          <div className="panel-card-body workflow-fixed-panel-body column-list-main-body">
            {children}
          </div>
        </article>
      </section>
    </section>
  )
}
