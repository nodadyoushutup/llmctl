import { Navigate, useParams } from 'react-router-dom'

function parseThreadId(value) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export default function ChatThreadRedirectPage() {
  const params = useParams()
  const threadId = parseThreadId(params.threadId)
  if (!threadId) {
    return <Navigate to="/chat" replace />
  }
  return <Navigate to={`/chat?thread_id=${threadId}`} replace />
}

