function joinClassNames(...values) {
  return values.filter((value) => typeof value === 'string' && value.trim()).join(' ')
}

export default function TableListEmptyState({
  message,
  className = '',
  role = 'status',
  ariaLive = 'polite',
  children = null,
}) {
  const rootClassName = joinClassNames('table-list-empty-state', className)

  return (
    <div className={rootClassName} role={role} aria-live={ariaLive}>
      <div className="table-list-empty-state-content">
        <p className="muted">{message}</p>
        {children ? <div className="table-list-empty-state-actions">{children}</div> : null}
      </div>
    </div>
  )
}
