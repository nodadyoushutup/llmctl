function joinClassNames(...values) {
  return values.filter((value) => typeof value === 'string' && value.trim()).join(' ')
}

export default function PanelHeader({
  title,
  titleTag = 'h3',
  titleClassName = '',
  className = '',
  actions = null,
  actionsClassName = '',
}) {
  const HeadingTag = titleTag
  const headerClassName = joinClassNames('panel-header', className)
  const headingClassName = joinClassNames('panel-header-title', titleClassName)
  const actionClassName = joinClassNames('panel-header-actions', actionsClassName)

  return (
    <div className={headerClassName}>
      {title != null ? <HeadingTag className={headingClassName}>{title}</HeadingTag> : null}
      {actions ? <div className={actionClassName}>{actions}</div> : null}
    </div>
  )
}
