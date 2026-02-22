import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { resolveApiUrl } from '../config/runtime'
import { HttpError } from '../lib/httpClient'
import { getAttachment } from '../lib/studioApi'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

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

export default function AttachmentDetailPage() {
  const { attachmentId } = useParams()
  const parsedAttachmentId = useMemo(() => parseId(attachmentId), [attachmentId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (!parsedAttachmentId) {
      return
    }
    let cancelled = false
    getAttachment(parsedAttachmentId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load attachment.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedAttachmentId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const attachment = payload?.attachment && typeof payload.attachment === 'object' ? payload.attachment : null
  const tasks = Array.isArray(payload?.tasks) ? payload.tasks : []
  const flowchartNodes = Array.isArray(payload?.flowchart_nodes) ? payload.flowchart_nodes : []
  const invalidId = parsedAttachmentId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid attachment id.' : state.error

  const fileHref = attachment ? resolveApiUrl(`/attachments/${attachment.id}/file`) : ''

  return (
    <section className="stack" aria-label="Attachment detail">
      <article className="card">
        <PanelHeader
          title={attachment ? attachment.file_name : 'Attachment'}
          actions={<Link to="/attachments" className="btn-link btn-secondary">All Attachments</Link>}
        />
        <p className="muted">Attachment metadata and relationship usage.</p>
        {loading ? <p>Loading attachment...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {attachment ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Type</dt>
                <dd>{attachment.content_type || '-'}</dd>
              </div>
              <div>
                <dt>Size</dt>
                <dd>{formatSize(attachment.size_bytes)}</dd>
              </div>
              <div>
                <dt>Bindings</dt>
                <dd>{attachment.binding_count ?? 0}</dd>
              </div>
            </dl>
            <div className="form-actions">
              <a href={fileHref} className="btn-link" target="_blank" rel="noreferrer">Open File</a>
            </div>
            {attachment.is_image ? (
              <img
                src={fileHref}
                alt={attachment.file_name || 'Attachment preview'}
                style={{ maxWidth: '100%', borderRadius: '0.6rem', border: '1px solid rgba(172, 205, 234, 0.28)' }}
              />
            ) : null}
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Task bindings</h2>
        {tasks.length === 0 ? <p>No task bindings.</p> : (
          <ul>
            {tasks.map((task) => (
              <li key={task.id}>Task {task.id} ({task.status || 'unknown'})</li>
            ))}
          </ul>
        )}
      </article>

      <article className="card">
        <h2>Flowchart node bindings</h2>
        {flowchartNodes.length === 0 ? <p>No flowchart node bindings.</p> : (
          <ul>
            {flowchartNodes.map((node) => (
              <li key={node.id}>
                <Link to={`/flowcharts/${node.flowchart_id}`}>{node.flowchart_name || `Flowchart ${node.flowchart_id}`}</Link>
                {' '}
                / {node.title || node.node_type || `Node ${node.id}`}
              </li>
            ))}
          </ul>
        )}
      </article>
    </section>
  )
}
