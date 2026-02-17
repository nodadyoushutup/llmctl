export default function LegacyFallbackNote({ path, label = 'Open legacy page' }) {
  const href = String(path || '/').startsWith('/') ? String(path || '/') : `/${String(path || '')}`

  return (
    <p className="legacy-note">
      Legacy fallback: <a href={href} target="_blank" rel="noreferrer">{label}</a>
    </p>
  )
}
