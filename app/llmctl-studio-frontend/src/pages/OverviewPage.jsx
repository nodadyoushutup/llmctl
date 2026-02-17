import { Link } from 'react-router-dom'

export default function OverviewPage() {
  return (
    <section className="card-grid" aria-label="Overview">
      <article className="card">
        <h2>Stage 5 scope</h2>
        <ul>
          <li>Stage 4 bootstrap remains the foundation for migration waves.</li>
          <li>Parity tracker now maps legacy Flask routes to React migration targets.</li>
          <li>Wave 1 chat routes are migrated to React with <code>/api</code> reads.</li>
        </ul>
      </article>
      <article className="card">
        <h2>Wave links</h2>
        <p>
          <Link to="/parity-checklist">Open Stage 5 parity checklist</Link>
        </p>
        <p>
          <Link to="/chat/activity">Open migrated chat activity flow</Link>
        </p>
      </article>
    </section>
  )
}
