function joinClassNames(...values) {
  return values.filter((value) => typeof value === 'string' && value.trim()).join(' ')
}

export default function HeaderPagination({
  ariaLabel,
  canGoPrev,
  canGoNext,
  onPrev,
  onNext,
  currentPage,
  totalPages,
  pageItems = null,
  onPageSelect = null,
  className = '',
}) {
  const navClassName = joinClassNames('pagination', className)
  const showPageItems = Array.isArray(pageItems) && typeof onPageSelect === 'function'

  return (
    <nav className={navClassName} aria-label={ariaLabel}>
      {canGoPrev ? (
        <button type="button" className="pagination-btn" onClick={onPrev}>
          Prev
        </button>
      ) : (
        <span className="pagination-btn is-disabled" aria-disabled="true">Prev</span>
      )}
      {showPageItems ? (
        <div className="pagination-pages">
          {pageItems.map((item, index) => {
            const itemType = String(item?.type || '')
            if (itemType === 'gap') {
              return <span key={`gap-${index}`} className="pagination-ellipsis">&hellip;</span>
            }
            const itemPage = Number.parseInt(String(item?.page || ''), 10)
            if (!Number.isInteger(itemPage) || itemPage <= 0) {
              return null
            }
            if (itemPage === currentPage) {
              return <span key={itemPage} className="pagination-link is-active" aria-current="page">{itemPage}</span>
            }
            return (
              <button
                key={itemPage}
                type="button"
                className="pagination-link"
                onClick={() => onPageSelect(itemPage)}
              >
                {itemPage}
              </button>
            )
          })}
        </div>
      ) : (
        <>
          <span className="pagination-link is-active" aria-current="page">{currentPage}</span>
          <span className="muted">/ {totalPages}</span>
        </>
      )}
      {canGoNext ? (
        <button type="button" className="pagination-btn" onClick={onNext}>
          Next
        </button>
      ) : (
        <span className="pagination-btn is-disabled" aria-disabled="true">Next</span>
      )}
    </nav>
  )
}
