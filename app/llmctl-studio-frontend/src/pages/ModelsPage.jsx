import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteModel, getModels, updateDefaultModel } from '../lib/studioApi'
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

export default function ModelsPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getModels()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load models.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const models = payload && Array.isArray(payload.models) ? payload.models : []

  function setBusy(modelId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[modelId] = true
      } else {
        delete next[modelId]
      }
      return next
    })
  }

  async function handleDelete(modelId) {
    if (!window.confirm('Delete this model?')) {
      return
    }
    setActionError('')
    setBusy(modelId, true)
    try {
      await deleteModel(modelId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete model.'))
    } finally {
      setBusy(modelId, false)
    }
  }

  async function handleDefault(modelId, isDefault) {
    setActionError('')
    setBusy(modelId, true)
    try {
      await updateDefaultModel(modelId, !isDefault)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update default model.'))
    } finally {
      setBusy(modelId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Models">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Models</h2>
            <p>Native React replacement for `/models` list and default model controls.</p>
          </div>
          <Link to="/models/new" className="btn-link">New Model</Link>
        </div>
        {state.loading ? <p>Loading models...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error && models.length === 0 ? <p>No models configured.</p> : null}
        {!state.loading && !state.error && models.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Default</th>
                  <th className="table-actions-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {models.map((model) => {
                  const href = `/models/${model.id}`
                  const busy = Boolean(busyById[model.id])
                  return (
                    <tr
                      key={model.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{model.name || `Model ${model.id}`}</Link>
                      </td>
                      <td>{model.provider_label || model.provider || '-'}</td>
                      <td>{model.model_name || '-'}</td>
                      <td>
                        <button
                          type="button"
                          className={model.is_default ? 'btn-link btn-secondary' : 'btn-link'}
                          disabled={busy}
                          onClick={() => handleDefault(model.id, Boolean(model.is_default))}
                        >
                          {model.is_default ? 'Default' : 'Set Default'}
                        </button>
                      </td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <Link
                            to={`/models/${model.id}/edit`}
                            className="icon-button"
                            aria-label="Edit model"
                            title="Edit model"
                          >
                            <ActionIcon name="edit" />
                          </Link>
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Delete model"
                            title="Delete model"
                            disabled={busy}
                            onClick={() => handleDelete(model.id)}
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
