import { useEffect, useMemo, useState } from 'react'
import { useFlash } from '../lib/flashMessages'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import {
  modelFieldLabel,
  normalizeProviderModelOptions,
  providerAllowsBlankModelSelection,
  providerUsesFreeformModelInput,
  resolveProviderModelName,
} from '../lib/modelFormOptions'
import { parseAdvancedConfigInput } from '../lib/modelAdvancedConfig'
import { resolveModelsListHref } from '../lib/modelsListState'
import { deleteModel, getModelEdit, updateModel } from '../lib/studioApi'

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

export default function ModelEditPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const flash = useFlash()
  const { modelId } = useParams()
  const parsedModelId = useMemo(() => parseId(modelId), [modelId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [busy, setBusy] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [fieldErrors, setFieldErrors] = useState({ name: '', advancedConfig: '' })
  const [form, setForm] = useState({ name: '', description: '', provider: 'codex', modelName: '' })
  const [advancedConfigText, setAdvancedConfigText] = useState('{}')
  const [initialSnapshot, setInitialSnapshot] = useState(null)
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
        const modelOptions = normalizeProviderModelOptions(payload?.model_options)
        const restConfig = { ...config }
        delete restConfig.model
        const advancedConfig = JSON.stringify(restConfig, null, 2)
        const resolvedModelName = resolveProviderModelName({
          provider,
          currentModelName: String(config.model || ''),
          modelOptions,
        })
        setAdvancedConfigText(advancedConfig)
        setForm({
          name: String(model.name || ''),
          description: String(model.description || ''),
          provider,
          modelName: resolvedModelName,
        })
        setInitialSnapshot({
          name: String(model.name || ''),
          description: String(model.description || ''),
          provider,
          modelName: resolvedModelName,
          advancedConfig,
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
  const modelOptions = useMemo(
    () => normalizeProviderModelOptions(state.payload?.model_options),
    [state.payload?.model_options],
  )
  const providerModelOptions = useMemo(() => {
    const options = modelOptions[form.provider]
    return Array.isArray(options) ? options : []
  }, [form.provider, modelOptions])
  const modelInputIsFreeform = providerUsesFreeformModelInput(form.provider)
  const advancedConfigValidation = useMemo(
    () => parseAdvancedConfigInput(advancedConfigText),
    [advancedConfigText],
  )
  const isDirty = useMemo(() => {
    if (!initialSnapshot) {
      return false
    }
    return (
      form.name !== initialSnapshot.name
      || form.description !== initialSnapshot.description
      || form.provider !== initialSnapshot.provider
      || form.modelName !== initialSnapshot.modelName
      || advancedConfigValidation.normalized !== initialSnapshot.advancedConfig
    )
  }, [advancedConfigValidation.normalized, form, initialSnapshot])
  const isFormValid = Boolean(String(form.name || '').trim()) && !advancedConfigValidation.error
  const canSubmit = !busy && !loading && !error && isDirty && isFormValid

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedModelId) {
      return
    }
    setBusy(true)
    const nextFieldErrors = { name: '', advancedConfig: '' }
    if (!String(form.name || '').trim()) {
      nextFieldErrors.name = 'Name is required.'
    }
    if (advancedConfigValidation.error) {
      nextFieldErrors.advancedConfig = advancedConfigValidation.error
    }
    try {
      setFieldErrors(nextFieldErrors)
      if (nextFieldErrors.name || nextFieldErrors.advancedConfig) {
        setBusy(false)
        return
      }
      const config = { ...advancedConfigValidation.config }
      if (form.modelName) {
        config.model = form.modelName
      } else {
        delete config.model
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
      flash.error(message)
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!parsedModelId || busy || deleteBusy || loading || error) {
      return
    }
    if (!window.confirm('Delete this model?')) {
      return
    }
    setDeleteBusy(true)
    try {
      await deleteModel(parsedModelId)
      flash.success(`Deleted model ${String(form.name || '').trim() || parsedModelId}.`)
      navigate(listHref)
    } catch (deleteError) {
      const message = errorMessage(deleteError, deleteError instanceof Error ? deleteError.message : 'Failed to delete model.')
      flash.error(message)
      setDeleteBusy(false)
    }
  }

  function handleCancel() {
    if (busy || deleteBusy) {
      return
    }
    if (isDirty && !window.confirm('Discard unsaved changes?')) {
      return
    }
    navigate(listHref)
  }

  return (
    <section className="stack" aria-label="Edit model">
      <article className="card">
        <PanelHeader
          title="Edit Model"
          titleTag="h2"
          actions={(
            <div className="table-actions">
              {parsedModelId ? <Link to={`/models/${parsedModelId}`} state={{ from: listHref }} className="btn-link btn-secondary">Back to Model</Link> : null}
              <Link to={listHref} className="btn-link btn-secondary">All Models</Link>
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete model"
                title="Delete model"
                onClick={() => { void handleDelete() }}
                disabled={busy || deleteBusy || loading || Boolean(error)}
              >
                <ActionIcon name="trash" />
              </button>
              <button
                type="button"
                className="btn-link btn-secondary"
                onClick={handleCancel}
                disabled={busy || deleteBusy}
              >
                Cancel
              </button>
              <button
                type="submit"
                form="model-edit-form"
                className="btn-link"
                disabled={!canSubmit || deleteBusy}
              >
                Save Model
              </button>
            </div>
          )}
        />
        <p className="panel-header-copy">Update provider selection and model policies.</p>
        {loading ? <p>Loading model...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {!loading && !error ? (
          <form id="model-edit-form" className="form-grid" onSubmit={handleSubmit}>
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
                onChange={(event) => {
                  const provider = event.target.value
                  setAdvancedConfigText('{}')
                  if (fieldErrors.advancedConfig) {
                    setFieldErrors((current) => ({ ...current, advancedConfig: '' }))
                  }
                  setForm((current) => ({
                    ...current,
                    provider,
                    modelName: resolveProviderModelName({
                      provider,
                      currentModelName: current.modelName,
                      modelOptions,
                    }),
                  }))
                }}
              >
                {providerOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>{modelFieldLabel(form.provider, providerOptions)}</span>
              {modelInputIsFreeform ? (
                <>
                  <input
                    type="text"
                    value={form.modelName}
                    list="edit-model-options"
                    onChange={(event) => setForm((current) => ({ ...current, modelName: event.target.value }))}
                  />
                  <datalist id="edit-model-options">
                    {providerModelOptions.map((option) => (
                      <option key={option} value={option} />
                    ))}
                  </datalist>
                </>
              ) : (
                <select
                  value={form.modelName}
                  onChange={(event) => setForm((current) => ({ ...current, modelName: event.target.value }))}
                >
                  {providerAllowsBlankModelSelection(form.provider) ? (
                    <option value="">Select model</option>
                  ) : null}
                  {providerModelOptions.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              )}
            </label>
            <div className="field field-span">
              <details>
                <summary>Advanced provider settings</summary>
                <div className="stack-sm" style={{ marginTop: '8px' }}>
                  <label className="field">
                    <span>Provider config JSON</span>
                    <textarea
                      rows={6}
                      value={advancedConfigText}
                      onChange={(event) => {
                        setAdvancedConfigText(event.target.value)
                        if (fieldErrors.advancedConfig) {
                          setFieldErrors((current) => ({ ...current, advancedConfig: '' }))
                        }
                      }}
                    />
                    {fieldErrors.advancedConfig ? <span className="error-text">{fieldErrors.advancedConfig}</span> : null}
                  </label>
                  <p className="muted">
                    Optional provider-specific overrides. Leave as <code>{'{}'}</code> to use defaults.
                  </p>
                </div>
              </details>
            </div>
            <label className="field field-span">
              <span>Description (optional)</span>
              <input
                type="text"
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
          </form>
        ) : null}
      </article>
    </section>
  )
}
