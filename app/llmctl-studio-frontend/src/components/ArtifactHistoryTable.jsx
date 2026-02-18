import { Link, useNavigate } from 'react-router-dom'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export default function ArtifactHistoryTable({ artifacts, emptyMessage, hrefForArtifact }) {
  const navigate = useNavigate()
  const rows = Array.isArray(artifacts) ? artifacts : []

  function handleRowClick(event, href) {
    if (!href || shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  if (rows.length === 0) {
    return (
      <p className="muted" style={{ marginTop: '12px' }}>
        {emptyMessage}
      </p>
    )
  }

  return (
    <div className="workflow-list-table-shell" style={{ marginTop: '12px' }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>Action</th>
            <th>Run variant</th>
            <th>Flowchart</th>
            <th>Created</th>
            <th className="table-actions-cell">Open</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((artifact) => {
            const artifactId = parseId(artifact?.id)
            const href = artifactId && typeof hrefForArtifact === 'function'
              ? String(hrefForArtifact(artifact) || '').trim()
              : ''
            const payloadAction = String(artifact?.payload?.action || '').trim()
            return (
              <tr
                key={artifactId || `${artifact?.created_at || 'artifact'}-${artifact?.variant_key || 'row'}`}
                className={href ? 'table-row-link' : undefined}
                data-href={href || undefined}
                onClick={(event) => handleRowClick(event, href)}
              >
                <td><p>{payloadAction || '-'}</p></td>
                <td><p className="muted">{artifact?.variant_key || '-'}</p></td>
                <td>
                  <p className="muted">
                    f{artifact?.flowchart_id || '-'} / n{artifact?.flowchart_node_id || '-'} / r{artifact?.flowchart_run_id || '-'}
                  </p>
                </td>
                <td><p className="muted">{artifact?.created_at || '-'}</p></td>
                <td className="table-actions-cell">
                  {href ? (
                    <Link
                      to={href}
                      className="icon-button"
                      aria-label={`Open artifact ${artifactId}`}
                      title={`Open artifact ${artifactId}`}
                    >
                      <i className="fa-solid fa-up-right-from-square" />
                    </Link>
                  ) : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
