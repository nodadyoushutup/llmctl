import { Link } from 'react-router-dom'

export default function OverviewPage() {
  return (
    <section className="card-grid" aria-label="Overview">
      <article className="card">
        <h2>Stage 5 scope</h2>
        <ul>
          <li>Stage 4 bootstrap remains the foundation for migration waves.</li>
          <li>Parity tracker now maps legacy Flask routes to React migration targets.</li>
          <li>Wave 1/2/3 domains now have native React coverage for core ops, planning, and memory/task surfaces.</li>
          <li>Wave 4 flowchart system is now on native React route coverage.</li>
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
        <p>
          <Link to="/execution-monitor">Open Wave 2 execution monitor</Link>
        </p>
        <p>
          <Link to="/agents">Open native agents domain</Link>
        </p>
        <p>
          <Link to="/runs">Open native runs domain</Link>
        </p>
        <p>
          <Link to="/nodes">Open native nodes domain</Link>
        </p>
        <p>
          <Link to="/quick">Open native quick task flow</Link>
        </p>
        <p>
          <Link to="/plans">Open native plans domain</Link>
        </p>
        <p>
          <Link to="/milestones">Open native milestones domain</Link>
        </p>
        <p>
          <Link to="/memories">Open native memories domain</Link>
        </p>
        <p>
          <Link to="/task-templates">Open native task templates domain</Link>
        </p>
        <p>
          <Link to="/flowcharts">Open native flowcharts domain</Link>
        </p>
      </article>
    </section>
  )
}
