import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getChatActivity } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

function parseThreadId(value) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export default function ChatActivityPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const eventClass = searchParams.get('event_class') || ''
  const eventType = searchParams.get('event_type') || ''
  const reasonCode = searchParams.get('reason_code') || ''
  const threadId = searchParams.get('thread_id') || ''
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const payload = await getChatActivity({
          limit: 200,
          eventClass,
          eventType,
          reasonCode,
          threadId,
        })
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (!cancelled) {
          let message = error instanceof HttpError ? error.message : 'Failed to load chat activity.'
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
  }, [eventClass, eventType, reasonCode, threadId])

  const events = useMemo(() => {
    if (!state.payload || typeof state.payload !== 'object') {
      return []
    }
    return Array.isArray(state.payload.events) ? state.payload.events : []
  }, [state.payload])

  const threads = useMemo(() => {
    if (state.payload && typeof state.payload === 'object' && Array.isArray(state.payload.threads)) {
      return state.payload.threads
    }
    const optionsById = new Map()
    for (const event of events) {
      if (!event || typeof event !== 'object') {
        continue
      }
      const parsedThreadId = parseThreadId(event.thread_id)
      if (!parsedThreadId || optionsById.has(parsedThreadId)) {
        continue
      }
      const title = String(event.thread_title || `Thread ${parsedThreadId}`)
      optionsById.set(parsedThreadId, { id: parsedThreadId, title })
    }
    return [...optionsById.values()]
  }, [events, state.payload])

  function applyFilters(event) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    const params = new URLSearchParams()
    const nextEventClass = String(formData.get('event_class') || '').trim()
    const nextEventType = String(formData.get('event_type') || '').trim()
    const nextReasonCode = String(formData.get('reason_code') || '').trim()
    const nextThreadId = String(formData.get('thread_id') || '').trim()
    if (nextEventClass) {
      params.set('event_class', nextEventClass)
    }
    if (nextEventType) {
      params.set('event_type', nextEventType)
    }
    if (nextReasonCode) {
      params.set('reason_code', nextReasonCode)
    }
    const parsedThreadId = parseThreadId(nextThreadId)
    if (parsedThreadId) {
      params.set('thread_id', String(parsedThreadId))
    }
    setSearchParams(params)
  }

  function resetFilters() {
    setSearchParams(new URLSearchParams())
  }

  function handleRowClick(event, href) {
    if (!href || shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Chat activity">
      <article className="card">
        <div className="card-header">
          <h2 className="section-title">Chat Activity</h2>
          <Link className="btn-link btn-secondary" to="/chat">
            <i className="fa-solid fa-comments" />
            back to chat
          </Link>
        </div>
        <p className="muted" style={{ marginTop: '12px' }}>
          Thread lifecycle, turn, retrieval/tool, compaction, and failure audit events.
        </p>
        <form
          key={`chat-activity-filters:${eventClass}:${eventType}:${reasonCode}:${threadId}`}
          className="form-grid"
          style={{ marginTop: '14px' }}
          onSubmit={applyFilters}
        >
          <div className="toolbar toolbar-wrap" style={{ margin: 0 }}>
            <div className="toolbar-group">
              <label htmlFor="chat-activity-class">Class</label>
              <input
                id="chat-activity-class"
                name="event_class"
                defaultValue={eventClass}
                placeholder="event class"
              />
            </div>
            <div className="toolbar-group">
              <label htmlFor="chat-activity-type">Type</label>
              <input
                id="chat-activity-type"
                name="event_type"
                defaultValue={eventType}
                placeholder="event type"
              />
            </div>
            <div className="toolbar-group">
              <label htmlFor="chat-activity-reason">Reason</label>
              <input
                id="chat-activity-reason"
                name="reason_code"
                defaultValue={reasonCode}
                placeholder="reason code"
              />
            </div>
            <div className="toolbar-group">
              <label htmlFor="chat-activity-thread">Thread</label>
              <select
                id="chat-activity-thread"
                name="thread_id"
                defaultValue={threadId}
              >
                <option value="">all threads</option>
                {threads.map((thread) => (
                  <option key={`thread-filter-${thread.id}`} value={thread.id}>
                    {thread.title || `Thread ${thread.id}`}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="toolbar" style={{ justifyContent: 'flex-start', margin: 0 }}>
            <button type="submit" className="btn-link btn-secondary">
              <i className="fa-solid fa-filter" />
              filter
            </button>
            <button type="button" className="btn-link" onClick={resetFilters}>
              <i className="fa-solid fa-rotate-right" />
              reset
            </button>
          </div>
        </form>

        {state.loading ? <p>Loading activity...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && events.length === 0 ? <p className="muted" style={{ marginTop: '16px' }}>No chat activity events yet.</p> : null}
        {!state.loading && !state.error && events.length > 0 ? (
          <div className="table-wrap" style={{ marginTop: '16px' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Thread</th>
                  <th>Class</th>
                  <th>Type</th>
                  <th>Reason</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {events.map((item) => {
                  const parsedThreadId = parseThreadId(item?.thread_id)
                  const href = parsedThreadId ? `/chat?thread_id=${parsedThreadId}` : ''
                  return (
                    <tr
                      key={`chat-activity-${item.id ?? `${item.created_at}-${item.event_type}`}`}
                      className={href ? 'table-row-link' : ''}
                      data-href={href || undefined}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <p>{item.thread_title || (parsedThreadId ? `Thread ${parsedThreadId}` : '-')}</p>
                        {item.turn_id ? <p className="table-note">turn {item.turn_id}</p> : null}
                      </td>
                      <td><p>{item.event_class || '-'}</p></td>
                      <td><p>{item.event_type || '-'}</p></td>
                      <td>
                        {item.reason_code ? <code>{item.reason_code}</code> : <span className="muted">-</span>}
                      </td>
                      <td>
                        <p>{item.created_at || '-'}</p>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </article>
    </section>
  )
}
