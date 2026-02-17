import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { createModel, getModelMeta } from '../lib/studioApi'

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

export default function ModelNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', provider: 'codex', modelName: '', configText: '{}' })

  useEffect(() => {
    let cancelled = false
    getModelMeta()
      .then((payload) => {
        if (cancelled) {
          return
        }
        const providerOptions = Array.isArray(payload?.provider_options) ? payload.provider_options : []
        const provider = providerOptions[0]?.value || 'codex'
        setForm((current) => ({ ...current, provider }))
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load model metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const providerOptions = Array.isArray(state.payload?.provider_options) ? state.payload.provider_options : []

  async function handleSubmit(event) {
    event.preventDefault()
    setActionError('')
    setBusy(true)
    try {
      const config = parseConfig(form.configText)
      if (form.modelName) {
        config.model = form.modelName
      }
      const payload = await createModel({
        name: form.name,
        description: form.description,
        provider: form.provider,
        config,
      })
      const modelId = payload?.model?.id
      if (modelId) {
        navigate(`/models/${modelId}`)
      } else {
        navigate('/models')
      }
    } catch (error) {
      setActionError(errorMessage(error, error instanceof Error ? error.message : 'Failed to create model.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="New model">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>New Model</h2>
            <p>Bind a provider with model and reasoning policies.</p>
          </div>
          <Link to="/models" className="btn-link btn-secondary">All Models</Link>
        </div>
        {state.loading ? <p>Loading model options...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error ? (
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
              <button type="submit" className="btn-link" disabled={busy}>Create Model</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}
