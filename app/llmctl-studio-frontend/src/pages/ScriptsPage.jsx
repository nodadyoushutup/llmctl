import { useCallback, useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteScript, getScripts } from '../lib/studioApi'
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

export default function ScriptsPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getScripts()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load scripts.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const scripts = payload && Array.isArray(payload.scripts) ? payload.scripts : []

  function setBusy(scriptId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[scriptId] = true
      } else {
        delete next[scriptId]
      }
      return next
    })
  }

  async function handleDelete(scriptId) {
    if (!window.confirm('Delete this script?')) {
      return
    }
    setActionError('')
    setBusy(scriptId, true)
    try {
      await deleteScript(scriptId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete script.'))
    } finally {
      setBusy(scriptId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Scripts">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Scripts</h2>
            <p>Upload helper scripts and bind them to task templates or flowchart nodes.</p>
          </div>
          <Link to="/scripts/new" className="btn-link">New Script</Link>
        </div>
        {state.loading ? <p>Loading scripts...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error && scripts.length === 0 ? <p>No scripts created yet.</p> : null}
        {!state.loading && !state.error && scripts.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>File name</th>
                  <th>Type</th>
                  <th>Description</th>
                  <th className="table-actions-cell">Delete</th>
                </tr>
              </thead>
              <tbody>
                {scripts.map((script) => {
                  const href = `/scripts/${script.id}`
                  const busy = Boolean(busyById[script.id])
                  return (
                    <tr
                      key={script.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{script.file_name || `Script ${script.id}`}</Link>
                      </td>
                      <td>{script.script_type_label || script.script_type || '-'}</td>
                      <td>
                        <p className="muted" style={{ fontSize: '12px' }}>{script.description || '-'}</p>
                      </td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Delete script"
                            title="Delete script"
                            disabled={busy}
                            onClick={() => handleDelete(script.id)}
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
