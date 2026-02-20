export default function ActionIcon({ name }) {
  if (name === 'play') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M4 2.5v11l9-5.5z" />
      </svg>
    )
  }
  if (name === 'stop') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M3 3h10v10H3z" />
      </svg>
    )
  }
  if (name === 'trash') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M6 2h4l1 1h3v2H2V3h3zm-1 4h2v6H5zm4 0h2v6H9zM4 6h1v6H4zm7 0h1v6h-1z" />
      </svg>
    )
  }
  if (name === 'up') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 3l5 6H3z" />
      </svg>
    )
  }
  if (name === 'down') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M3 7h10l-5 6z" />
      </svg>
    )
  }
  if (name === 'save') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M2 2h10l2 2v10H2zm2 1v4h7V3zm0 6v3h8V9z" />
      </svg>
    )
  }
  if (name === 'edit') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M11.9 1.8l2.3 2.3-7.9 7.9-3 .7.7-3zM2 13h12v1H2z" />
      </svg>
    )
  }
  if (name === 'plus') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M7 3h2v4h4v2H9v4H7V9H3V7h4z" />
      </svg>
    )
  }
  if (name === 'check') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M6.4 12.1 2.8 8.5l1.4-1.4 2.2 2.2 5.4-5.4 1.4 1.4z" />
      </svg>
    )
  }
  if (name === 'star') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 1.6l1.8 3.7 4.1.6-3 2.9.7 4.2L8 11.1 4.4 13l.7-4.2-3-2.9 4.1-.6zM8 3.8 7 5.9l-2.3.3 1.7 1.6-.4 2.3L8 9l2 1-.4-2.2 1.7-1.6-2.3-.3z" />
      </svg>
    )
  }
  if (name === 'star-filled') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 1.6l1.8 3.7 4.1.6-3 2.9.7 4.2L8 11.1 4.4 13l.7-4.2-3-2.9 4.1-.6z" />
      </svg>
    )
  }
  return null
}
