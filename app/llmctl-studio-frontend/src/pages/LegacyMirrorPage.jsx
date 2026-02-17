import { useMemo } from 'react'
import { useLocation } from 'react-router-dom'

function buildLegacyUrl(pathname, search) {
  const path = String(pathname || '/').startsWith('/') ? String(pathname || '/') : `/${String(pathname || '')}`
  const query = String(search || '')
  return `/api${path}${query}`
}

export default function LegacyMirrorPage() {
  const location = useLocation()
  const legacyUrl = useMemo(
    () => buildLegacyUrl(location.pathname, location.search),
    [location.pathname, location.search],
  )

  return (
    <section className="stack" aria-label="Legacy mirror">
      <article className="card">
        <h2>Legacy route bridge</h2>
        <p>
          This route is running in bridge mode during Stage 5. The legacy Flask GUI is rendered inside
          the React shell so behavior parity is preserved while native React replacements are delivered.
        </p>
        <p>
          <strong>Mirrored path:</strong> <code>{legacyUrl}</code>
        </p>
        <p>
          <a href={legacyUrl} target="_blank" rel="noreferrer">
            Open legacy page in a new tab
          </a>
        </p>
      </article>

      <article className="card legacy-frame-card">
        <iframe title="Legacy Studio page" src={legacyUrl} className="legacy-frame" loading="lazy" />
      </article>
    </section>
  )
}
