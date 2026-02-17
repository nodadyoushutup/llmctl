import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteAttachment, getAttachments } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

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

function formatSize(sizeBytes) {
  const value = Number(sizeBytes)
  if (!Number.isFinite(value) || value < 0) {
    return '-'
  }
  if (value < 1024) {
    return `${value} B`
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

export default function AttachmentsPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getAttachments()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load attachments.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const attachments = payload && Array.isArray(payload.attachments) ? payload.attachments : []

  function setBusy(attachmentId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[attachmentId] = true
      } else {
        delete next[attachmentId]
      }
      return next
    })
  }

  async function handleDelete(attachmentId) {
    if (!window.confirm('Delete this attachment?')) {
      return
    }
    setActionError('')
    setBusy(attachmentId, true)
    try {
      await deleteAttachment(attachmentId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete attachment.'))
    } finally {
      setBusy(attachmentId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Attachments">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Attachments</h2>
            <p>Native React replacement for `/attachments` list and row actions.</p>
          </div>
        </div>
        {state.loading ? <p>Loading attachments...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error && attachments.length === 0 ? <p>No attachments found.</p> : null}
        {!state.loading && !state.error && attachments.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>Bindings</th>
                  <th>Updated</th>
                  <th className="table-actions-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {attachments.map((attachment) => {
                  const href = `/attachments/${attachment.id}`
                  const busy = Boolean(busyById[attachment.id])
                  return (
                    <tr
                      key={attachment.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{attachment.file_name || `Attachment ${attachment.id}`}</Link>
                      </td>
                      <td>{attachment.content_type || '-'}</td>
                      <td>{formatSize(attachment.size_bytes)}</td>
                      <td>{attachment.binding_count ?? 0}</td>
                      <td>{attachment.updated_at || '-'}</td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Delete attachment"
                            title="Delete attachment"
                            disabled={busy}
                            onClick={() => handleDelete(attachment.id)}
                          >
                            <ActionIcon name="trash" />
                          </button>
                        </div>
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
