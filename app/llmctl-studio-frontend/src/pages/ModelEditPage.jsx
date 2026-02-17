import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getModelEdit, updateModel } from '../lib/studioApi'

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

function parseConfig(configText) {
  if (!String(configText || '').trim()) {
    return {}
  }
  const parsed = JSON.parse(configText)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Config must be a JSON object.')
  }
  return parsed
}

export default function ModelEditPage() {
  const navigate = useNavigate()
  const { modelId } = useParams()
  const parsedModelId = useMemo(() => parseId(modelId), [modelId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', provider: 'codex', modelName: '', configText: '{}' })

  useEffect(() => {
    if (!parsedModelId) {
      return
    }
    let cancelled = false
    getModelEdit(parsedModelId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        const model = payload?.model && typeof payload.model === 'object' ? payload.model : {}
        const providerOptions = Array.isArray(payload?.provider_options) ? payload.provider_options : []
        const provider = String(model.provider || providerOptions[0]?.value || 'codex')
        const config = model.config && typeof model.config === 'object' ? model.config : {}
        setForm({
          name: String(model.name || ''),
          description: String(model.description || ''),
          provider,
          modelName: String(config.model || ''),
          configText: model.config_json || JSON.stringify(config, null, 2),
        })
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load model edit metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedModelId])
  const invalidId = parsedModelId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid model id.' : state.error

  const providerOptions = Array.isArray(state.payload?.provider_options) ? state.payload.provider_options : []

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedModelId) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      const config = parseConfig(form.configText)
      if (form.modelName) {
        config.model = form.modelName
      }
      await updateModel(parsedModelId, {
        name: form.name,
        description: form.description,
        provider: form.provider,
        config,
      })
      navigate(`/models/${parsedModelId}`)
    } catch (error) {
      setActionError(errorMessage(error, error instanceof Error ? error.message : 'Failed to update model.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit model">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Edit Model</h2>
            <p>Update provider selection and model policies.</p>
          </div>
          <div className="table-actions">
            {parsedModelId ? <Link to={`/models/${parsedModelId}`} className="btn-link btn-secondary">Back to Model</Link> : null}
            <Link to="/models" className="btn-link btn-secondary">All Models</Link>
          </div>
        </div>
        {loading ? <p>Loading model...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!loading && !error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field">
              <span>Name</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Provider</span>
              <select
                value={form.provider}
                onChange={(event) => setForm((current) => ({ ...current, provider: event.target.value }))}
              >
                {providerOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Model name (config.model)</span>
              <input
                type="text"
                value={form.modelName}
                onChange={(event) => setForm((current) => ({ ...current, modelName: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Description (optional)</span>
              <input
                type="text"
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Config JSON</span>
              <textarea
                value={form.configText}
                onChange={(event) => setForm((current) => ({ ...current, configText: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy}>Save Model</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}
