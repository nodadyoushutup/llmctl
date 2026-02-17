import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <section className="card-grid">
      <article className="card">
        <h2>Route not found</h2>
        <p>This route is not mapped in the React router.</p>
        <p>
          <Link to="/agents">Open agents</Link>
        </p>
      </article>
    </section>
  )
}
