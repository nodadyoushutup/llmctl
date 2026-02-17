import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import LegacyFallbackNote from '../components/LegacyFallbackNote'
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

  return (
    <section className="stack" aria-label="Chat thread detail">
      <article className="card">
        <h2>Chat thread detail</h2>
        <p>
          <Link to="/chat/activity">Back to chat activity</Link>
        </p>
        <LegacyFallbackNote path="/chat" label="Open /chat" />
      </article>

      <article className="card">
        <h2>Thread payload</h2>
        {state.loading ? <p>Loading thread...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {state.payload ? <pre>{JSON.stringify(state.payload, null, 2)}</pre> : null}
      </article>
    </section>
  )
}
