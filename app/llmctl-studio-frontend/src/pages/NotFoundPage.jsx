import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <section className="card-grid">
      <article className="card">
        <h2>Route not found</h2>
        <p>This route is not part of the current migration wave.</p>
        <p>
          <Link to="/">Return to overview</Link>
        </p>
      </article>
    </section>
  )
}
