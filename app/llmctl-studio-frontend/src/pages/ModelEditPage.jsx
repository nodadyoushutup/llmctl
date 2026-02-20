import { useEffect, useMemo, useState } from 'react'
import { useFlash } from '../lib/flashMessages'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { resolveModelsListHref } from '../lib/modelsListState'
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

function isConfigParseError(error, message) {
  return error instanceof SyntaxError || message === 'Config must be a JSON object.'
}

export default function ModelEditPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const flash = useFlash()
  const { modelId } = useParams()
  const parsedModelId = useMemo(() => parseId(modelId), [modelId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [busy, setBusy] = useState(false)
  const [fieldErrors, setFieldErrors] = useState({ name: '', configText: '' })
  const [form, setForm] = useState({ name: '', description: '', provider: 'codex', modelName: '', configText: '{}' })
  const listHref = useMemo(() => resolveModelsListHref(location.state?.from), [location.state])

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
      await updateModel(parsedModelId, {
        name: form.name,
        description: form.description,
        provider: form.provider,
        config,
      })
      flash.success(`Saved model ${String(form.name || '').trim() || parsedModelId}.`)
      navigate(`/models/${parsedModelId}`, { state: { from: listHref } })
    } catch (error) {
      const message = errorMessage(error, error instanceof Error ? error.message : 'Failed to update model.')
      if (isConfigParseError(error, message)) {
        setFieldErrors((current) => ({
          ...current,
          configText: error instanceof SyntaxError ? 'Config must be valid JSON.' : message,
        }))
      } else {
        flash.error(message)
      }
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
            {parsedModelId ? <Link to={`/models/${parsedModelId}`} state={{ from: listHref }} className="btn-link btn-secondary">Back to Model</Link> : null}
            <Link to={listHref} className="btn-link btn-secondary">All Models</Link>
          </div>
        </div>
        {loading ? <p>Loading model...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {!loading && !error ? (
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
              <button type="submit" className="btn-link" disabled={busy}>Save Model</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}
