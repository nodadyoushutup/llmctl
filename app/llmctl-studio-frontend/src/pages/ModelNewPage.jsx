import { useEffect, useMemo, useState } from 'react'
import { useFlash } from '../lib/flashMessages'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { resolveModelsListHref } from '../lib/modelsListState'
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
  const location = useLocation()
  const flash = useFlash()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [busy, setBusy] = useState(false)
  const [fieldErrors, setFieldErrors] = useState({ name: '', configText: '' })
  const [form, setForm] = useState({ name: '', description: '', provider: 'codex', modelName: '', configText: '{}' })
  const listHref = useMemo(() => resolveModelsListHref(location.state?.from), [location.state])

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
    setBusy(true)
    const nextFieldErrors = { name: '', configText: '' }
    if (!String(form.name || '').trim()) {
      nextFieldErrors.name = 'Name is required.'
    }
    try {
      const config = parseConfig(form.configText)
      setFieldErrors(nextFieldErrors)
      if (nextFieldErrors.name) {
        setBusy(false)
        return
      }
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
      flash.success(`Created model ${String(form.name || '').trim() || 'profile'}.`)
      if (modelId) {
        navigate(`/models/${modelId}`, { state: { from: listHref } })
      } else {
        navigate(listHref)
      }
    } catch (error) {
      const message = errorMessage(error, error instanceof Error ? error.message : 'Failed to create model.')
      if (message === 'Config must be a JSON object.' || message.startsWith('Unexpected token')) {
        setFieldErrors((current) => ({ ...current, configText: message }))
      } else {
        flash.error(message)
      }
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
          <Link to={listHref} className="btn-link btn-secondary">All Models</Link>
        </div>
        {state.loading ? <p>Loading model options...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field">
              <span>Name</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(event) => {
                  const value = event.target.value
                  setForm((current) => ({ ...current, name: value }))
                  if (fieldErrors.name) {
                    setFieldErrors((current) => ({ ...current, name: '' }))
                  }
                }}
              />
              {fieldErrors.name ? <span className="error-text">{fieldErrors.name}</span> : null}
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
                onChange={(event) => {
                  const value = event.target.value
                  setForm((current) => ({ ...current, configText: value }))
                  if (fieldErrors.configText) {
                    setFieldErrors((current) => ({ ...current, configText: '' }))
                  }
                }}
              />
              {fieldErrors.configText ? <span className="error-text">{fieldErrors.configText}</span> : null}
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
