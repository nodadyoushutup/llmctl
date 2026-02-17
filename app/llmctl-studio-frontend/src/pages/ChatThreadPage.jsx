import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getChatThread } from '../lib/studioApi'

export default function ChatThreadPage() {
  const params = useParams()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  const threadId = useMemo(() => {
    const parsed = Number.parseInt(String(params.threadId || ''), 10)
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null
  }, [params.threadId])

  useEffect(() => {
    let cancelled = false

    async function load() {
      if (!threadId) {
        setState({ loading: false, payload: null, error: 'Invalid thread id.' })
        return
      }

      try {
        const payload = await getChatThread(threadId)
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (!cancelled) {
          let message = error instanceof HttpError ? error.message : 'Failed to load chat thread.'
          if (error instanceof HttpError && error.isAuthError) {
            message = `${message} Sign in to Studio if authentication is enabled.`
          }
          setState({ loading: false, payload: null, error: message })
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [threadId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const messages = payload && Array.isArray(payload.messages) ? payload.messages : []
  const mcpServers = payload && Array.isArray(payload.mcp_servers) ? payload.mcp_servers : []
  const ragCollections = payload && Array.isArray(payload.rag_collections) ? payload.rag_collections : []
  const latestTurn = payload && payload.latest_turn && typeof payload.latest_turn === 'object'
    ? payload.latest_turn
    : null

  return (
    <section className="stack" aria-label="Chat thread detail">
      <article className="card">
        <div className="card-header">
          <div>
            <h2 className="section-title">{payload?.title || 'Chat Thread'}</h2>
          </div>
          <Link className="btn-link btn-secondary" to="/chat/activity">
            <i className="fa-solid fa-arrow-left" />
            back to activity
          </Link>
        </div>
        {state.loading ? <p>Loading thread...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {payload ? (
          <div className="stack" style={{ marginTop: '14px' }}>
            <div className="grid grid-2">
              <div className="subcard">
                <p className="eyebrow">thread</p>
                <div className="stack" style={{ marginTop: '10px' }}>
                  <p className="muted">id: {payload.id}</p>
                  <p className="muted">status: {payload.status || '-'}</p>
                  <p className="muted">model: {payload.model_name || '-'}</p>
                  <p className="muted">complexity: {payload.response_complexity_label || payload.response_complexity || '-'}</p>
                  <p className="muted">updated: {payload.updated_at || '-'}</p>
                </div>
              </div>
              <div className="subcard">
                <p className="eyebrow">selectors</p>
                <div className="stack" style={{ marginTop: '10px' }}>
                  <p className="muted">
                    MCP:
                    {' '}
                    {mcpServers.length > 0
                      ? mcpServers.map((server) => server.name || server.server_key || server.id).join(', ')
                      : 'none'}
                  </p>
                  <p className="muted">
                    RAG:
                    {' '}
                    {ragCollections.length > 0 ? ragCollections.join(', ') : 'none'}
                  </p>
                </div>
              </div>
            </div>

            {latestTurn ? (
              <div className="subcard">
                <p className="eyebrow">latest turn</p>
                <div className="grid grid-2" style={{ marginTop: '10px' }}>
                  <p className="muted">status: {latestTurn.status || '-'}</p>
                  <p className="muted">reason: {latestTurn.reason_code || '-'}</p>
                  <p className="muted">tokens before: {latestTurn.context_usage_before ?? '-'}</p>
                  <p className="muted">tokens after: {latestTurn.context_usage_after ?? '-'}</p>
                </div>
              </div>
            ) : null}

            {payload.compaction_summary_text ? (
              <div className="subcard">
                <p className="eyebrow">compaction summary</p>
                <pre style={{ marginTop: '10px', whiteSpace: 'pre-wrap' }}>{payload.compaction_summary_text}</pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </article>

      <article className="card">
        <div className="card-header">
          <h2 className="section-title">Messages</h2>
        </div>
        {!state.loading && !state.error && messages.length === 0 ? <p className="muted">No messages in this thread yet.</p> : null}
        {!state.loading && !state.error && messages.length > 0 ? (
          <div className="stack" style={{ marginTop: '14px' }}>
            {messages.map((message) => (
              <div key={message.id || `${message.role}-${message.created_at}`} className="subcard">
                <div className="row-between">
                  <p className="eyebrow">{String(message.role || 'assistant').toLowerCase()}</p>
                  <p className="muted" style={{ fontSize: '12px' }}>{message.created_at || '-'}</p>
                </div>
                <p style={{ marginTop: '8px', whiteSpace: 'pre-wrap' }}>{message.content || ''}</p>
              </div>
            ))}
          </div>
        ) : null}
      </article>
    </section>
  )
}
