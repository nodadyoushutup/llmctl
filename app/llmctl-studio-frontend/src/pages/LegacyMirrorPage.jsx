import { useMemo } from 'react'
import { useLocation } from 'react-router-dom'

function buildLegacyUrl(pathname, search) {
  const rawPath = String(pathname || '/')
  const normalizedPath = rawPath === '/' ? '/overview' : rawPath
  const path = normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`
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
    <section className="legacy-mirror-shell" aria-label="Legacy mirror">
      <iframe title="Legacy Studio page" src={legacyUrl} className="legacy-frame legacy-frame-full" loading="lazy" />
    </section>
  )
}
