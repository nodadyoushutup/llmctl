import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getRagChatMeta, sendRagChat } from '../lib/studioApi'

function errorMessage(error, fallback) {
  if (error instanceof HttpError) {
    if (error.isAuthError) {
      return `${error.message} Sign in to Studio if authentication is enabled.`
    }
    return error.message
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

export default function RagChatPage() {
  const [metaState, setMetaState] = useState({ loading: true, payload: null, error: '' })
  const [message, setMessage] = useState('')
  const [topK, setTopK] = useState(5)
  const [historyLimit, setHistoryLimit] = useState('')
  const [verbosity, setVerbosity] = useState('')
  const [selectedCollections, setSelectedCollections] = useState([])
  const [busy, setBusy] = useState(false)
  const [chatError, setChatError] = useState('')
  const [chatResult, setChatResult] = useState(null)

  const refresh = useCallback(async () => {
    setMetaState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getRagChatMeta()
      setMetaState({ loading: false, payload, error: '' })
      const defaultTopK = Number.parseInt(String(payload?.chat_top_k ?? ''), 10)
      if (Number.isInteger(defaultTopK) && defaultTopK > 0) {
        setTopK(defaultTopK)
      }
      const defaultVerbosity = String(payload?.chat_verbosity || '').trim()
      if (defaultVerbosity) {
        setVerbosity(defaultVerbosity)
      }
      if (Array.isArray(payload?.collections)) {
        const ids = payload.collections
          .map((item) => String(item?.id || '').trim())
          .filter(Boolean)
        setSelectedCollections(ids)
      }
    } catch (error) {
      setMetaState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load RAG chat metadata.') })
    }
  }, [])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const payload = await getRagChatMeta()
        if (!active) {
          return
        }
        setMetaState({ loading: false, payload, error: '' })
        const defaultTopK = Number.parseInt(String(payload?.chat_top_k ?? ''), 10)
        if (Number.isInteger(defaultTopK) && defaultTopK > 0) {
          setTopK(defaultTopK)
        }
        const defaultVerbosity = String(payload?.chat_verbosity || '').trim()
        if (defaultVerbosity) {
          setVerbosity(defaultVerbosity)
        }
        if (Array.isArray(payload?.collections)) {
          const ids = payload.collections
            .map((item) => String(item?.id || '').trim())
            .filter(Boolean)
          setSelectedCollections(ids)
        }
      } catch (error) {
        if (active) {
          setMetaState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load RAG chat metadata.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const payload = metaState.payload && typeof metaState.payload === 'object' ? metaState.payload : null
  const collections = useMemo(() => (payload && Array.isArray(payload.collections) ? payload.collections : []), [payload])

  function toggleCollection(collectionId) {
    setSelectedCollections((current) => (
      current.includes(collectionId)
        ? current.filter((item) => item !== collectionId)
        : [...current, collectionId]
    ))
  }

  async function submitChat(event) {
    event.preventDefault()
    setChatError('')
    setChatResult(null)
    if (!message.trim()) {
      setChatError('Message is required.')
      return
    }
    setBusy(true)
    try {
      const result = await sendRagChat({
        message,
        collections: selectedCollections,
        topK,
        historyLimit,
        verbosity,
      })
      setChatResult(result)
    } catch (error) {
      setChatError(errorMessage(error, 'Failed to run RAG chat query.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="RAG chat">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>RAG Chat</h2>
            <p>Ask questions against indexed collections with retrieval controls.</p>
          </div>
          <div className="table-actions">
            <Link to="/rag/sources" className="btn-link btn-secondary">RAG Sources</Link>
            <Link to="/settings/runtime/rag" className="btn-link btn-secondary">RAG Settings</Link>
            <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
          </div>
        </div>
        {metaState.loading ? <p>Loading RAG chat metadata...</p> : null}
        {metaState.error ? <p className="error-text">{metaState.error}</p> : null}
        {payload?.missing_api_key ? <p className="error-text">{String(payload.missing_api_key)}</p> : null}
      </article>

      {!metaState.loading && !metaState.error ? (
        <article className="card">
          <h2>Ask</h2>
          <form className="form-grid" onSubmit={submitChat}>
            <label>
              Message
              <textarea
                rows={6}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Ask a question against selected collections"
              />
            </label>
            <div className="key-value-grid">
              <label>
                Top K
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(event) => setTopK(Number.parseInt(event.target.value, 10) || 5)}
                />
              </label>
              <label>
                History limit
                <input value={historyLimit} onChange={(event) => setHistoryLimit(event.target.value)} placeholder="Optional" />
              </label>
              <label>
                Verbosity
                <input value={verbosity} onChange={(event) => setVerbosity(event.target.value)} placeholder="low | medium | high" />
              </label>
            </div>
            <div>
              <p><strong>Collections</strong></p>
              {collections.length === 0 ? <p>No collections available.</p> : null}
              <div className="toolbar-group">
                {collections.map((collection, index) => {
                  const collectionId = String(collection?.id || '').trim()
                  const label = String(collection?.label || collection?.name || collectionId || `Collection ${index + 1}`)
                  return (
                    <label key={`${collectionId || 'collection'}-${index}`}>
                      <input
                        type="checkbox"
                        checked={selectedCollections.includes(collectionId)}
                        onChange={() => toggleCollection(collectionId)}
                      />
                      {' '}{label}
                    </label>
                  )
                })}
              </div>
            </div>
            <div className="table-actions">
              <button type="submit" className="btn-link" disabled={busy}>{busy ? 'Sending...' : 'Send'}</button>
            </div>
          </form>
          {chatError ? <p className="error-text">{chatError}</p> : null}
        </article>
      ) : null}

      {chatResult ? (
        <article className="card">
          <h2>Response</h2>
          <p>{chatResult.reply || chatResult.answer || '-'}</p>
          <h3>Retrieval context</h3>
          {Array.isArray(chatResult.retrieval_context) && chatResult.retrieval_context.length > 0 ? (
            <ul className="stack">
              {chatResult.retrieval_context.map((item, index) => (
                <li key={`${item?.source_id || 'ctx'}-${index}`}>
                  <strong>{item?.collection || 'collection'}:</strong> {item?.text || '-'}
                </li>
              ))}
            </ul>
          ) : <p>No retrieval snippets returned.</p>}
        </article>
      ) : null}
    </section>
  )
}
