import { Link } from 'react-router-dom'
import { buildParitySummary, parityChecklist, parityStatusLabels } from '../parity/checklist'

function statusClassName(status) {
  return `status-chip status-${status}`
}

export default function ParityChecklistPage() {
  const summary = buildParitySummary(parityChecklist)

  return (
    <section className="stack" aria-label="Parity checklist">
      <article className="card">
        <h2>Stage 5 parity tracker</h2>
        <p>
          This checklist is derived from the existing Flask GUI route/template surface and tracks
          migration waves to React.
        </p>
        <div className="stats-grid">
          <div className="stat-item">
            <span>Total</span>
            <strong>{summary.total}</strong>
          </div>
          <div className="stat-item">
            <span>Native React</span>
            <strong>{summary.migrated}</strong>
          </div>
          <div className="stat-item">
            <span>Legacy Bridge</span>
            <strong>{summary.bridged}</strong>
          </div>
        </div>
      </article>

      <article className="card">
        <h2>Wave items</h2>
        <div className="table-wrap">
          <table className="parity-table">
            <thead>
              <tr>
                <th>Wave</th>
                <th>Area</th>
                <th>Status</th>
                <th>React route</th>
                <th>Legacy route</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {parityChecklist.map((item) => (
                <tr key={`${item.wave}-${item.area}`}>
                  <td>{item.wave}</td>
                  <td>{item.area}</td>
                  <td>
                    <span className={statusClassName(item.status)}>
                      {parityStatusLabels[item.status] || parityStatusLabels.bridged}
                    </span>
                  </td>
                  <td>
                    {item.reactPath.startsWith('/') && !item.reactPath.includes(':') ? (
                      <Link to={item.reactPath}>{item.reactPath}</Link>
                    ) : (
                      <code>{item.reactPath}</code>
                    )}
                  </td>
                  <td>
                    {item.legacyPath.startsWith('/') ? (
                      <a href={item.legacyPath} target="_blank" rel="noreferrer">
                        {item.legacyPath}
                      </a>
                    ) : (
                      <code>{item.legacyPath}</code>
                    )}
                  </td>
                  <td>{item.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  )
}
