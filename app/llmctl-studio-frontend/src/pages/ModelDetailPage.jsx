import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { resolveModelsListHref } from '../lib/modelsListState'
import { getModel } from '../lib/studioApi'

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

function formatConfigLabel(key) {
  return String(key || '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

const LEGACY_SDK_CONFIG_KEYS = new Set([
  'approval_policy',
  'network_access',
  'sandbox_mode',
  'shell_env_ignore_default_excludes',
  'shell_env_inherit',
  'notice_hide_enabled',
  'notice_hide_key',
  'notice_migration_from',
  'notice_migration_to',
  'approval_mode',
  'sandbox',
  'extra_args',
])

function toProfileEntries(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    return []
  }
  return Object.entries(config)
    .filter(([key, value]) => {
      if (key === 'model') {
        return false
      }
      if (value == null) {
        return false
      }
      if (typeof value === 'string' && !value.trim()) {
        return false
      }
      return true
    })
    .map(([key, value]) => ({
      key,
      label: formatConfigLabel(key),
      value: typeof value === 'object' ? JSON.stringify(value) : String(value),
    }))
}

function splitProfileEntries(entries) {
  const primary = []
  const legacy = []
  entries.forEach((entry) => {
    if (LEGACY_SDK_CONFIG_KEYS.has(entry.key)) {
      legacy.push(entry)
      return
    }
    primary.push(entry)
  })
  return { primary, legacy }
}

export default function ModelDetailPage() {
  const location = useLocation()
  const { modelId } = useParams()
  const parsedModelId = useMemo(() => parseId(modelId), [modelId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const listHref = useMemo(() => resolveModelsListHref(location.state?.from), [location.state])

  useEffect(() => {
    if (!parsedModelId) {
      return
    }
    let cancelled = false
    getModel(parsedModelId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load model.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedModelId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const model = payload?.model && typeof payload.model === 'object' ? payload.model : null
  const nodes = Array.isArray(payload?.attached_nodes) ? payload.attached_nodes : []
  const tasks = Array.isArray(payload?.attached_tasks) ? payload.attached_tasks : []
  const profileEntries = useMemo(() => toProfileEntries(model?.config), [model?.config])
  const { primary: primaryProfileEntries, legacy: legacyProfileEntries } = useMemo(
    () => splitProfileEntries(profileEntries),
    [profileEntries],
  )
  const invalidId = parsedModelId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid model id.' : state.error

  return (
    <section className="stack" aria-label="Model detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{model ? model.name : 'Model'}</h2>
            <p>{model?.description || 'Model settings and binding usage.'}</p>
          </div>
          <div className="table-actions">
            {model ? <Link to={`/models/${model.id}/edit`} state={{ from: listHref }} className="btn-link">Edit</Link> : null}
            <Link to={listHref} className="btn-link btn-secondary">All Models</Link>
          </div>
        </div>
        {loading ? <p>Loading model...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {model ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Provider</dt>
                <dd>{model.provider_label || model.provider || '-'}</dd>
              </div>
              <div>
                <dt>Configured model</dt>
                <dd>{model.model_name || '-'}</dd>
              </div>
              <div>
                <dt>Default</dt>
                <dd>{model.is_default ? 'Yes' : 'No'}</dd>
              </div>
            </dl>
            <section className="stack-sm" aria-label="Runtime profile">
              <h3>Runtime profile</h3>
              {primaryProfileEntries.length === 0 ? <p className="muted">No active provider-specific overrides configured.</p> : (
                <dl className="kv-grid">
                  {primaryProfileEntries.map((entry) => (
                    <div key={entry.key}>
                      <dt>{entry.label}</dt>
                      <dd>{entry.value}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {legacyProfileEntries.length > 0 ? (
                <details>
                  <summary>{legacyProfileEntries.length} legacy override(s) hidden</summary>
                  <dl className="kv-grid">
                    {legacyProfileEntries.map((entry) => (
                      <div key={entry.key}>
                        <dt>{entry.label}</dt>
                        <dd>{entry.value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              ) : null}
            </section>
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Flowchart node bindings</h2>
        {nodes.length === 0 ? <p>No flowchart node bindings.</p> : (
          <ul>
            {nodes.map((node) => (
              <li key={node.id}>
                <Link to={`/flowcharts/${node.flowchart_id}`}>{node.flowchart_name || `Flowchart ${node.flowchart_id}`}</Link>
                {' '}
                / {node.title || node.node_type || `Node ${node.id}`}
              </li>
            ))}
          </ul>
        )}
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
    </section>
  )
}
