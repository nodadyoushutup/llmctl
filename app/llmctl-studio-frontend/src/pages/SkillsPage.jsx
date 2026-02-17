import { useCallback, useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteSkill, getSkills } from '../lib/studioApi'
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

export default function SkillsPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getSkills()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load skills.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const skills = payload && Array.isArray(payload.skills) ? payload.skills : []

  function setBusy(skillId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[skillId] = true
      } else {
        delete next[skillId]
      }
      return next
    })
  }

  async function handleDelete(skillId) {
    if (!window.confirm('Delete this skill?')) {
      return
    }
    setActionError('')
    setBusy(skillId, true)
    try {
      await deleteSkill(skillId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete skill.'))
    } finally {
      setBusy(skillId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Skills">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Skills</h2>
            <p>First-class skill packages assigned to Agents.</p>
          </div>
          <div className="table-actions">
            <Link to="/skills/import" className="btn-link btn-secondary">Import Skill</Link>
            <Link to="/skills/new" className="btn-link">New Skill</Link>
          </div>
        </div>
        {state.loading ? <p>Loading skills...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error && skills.length === 0 ? <p>No skills created yet.</p> : null}
        {!state.loading && !state.error && skills.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Slug</th>
                  <th>Status</th>
                  <th>Latest version</th>
                  <th>Agent bindings</th>
                  <th className="table-actions-cell">Delete</th>
                </tr>
              </thead>
              <tbody>
                {skills.map((skill) => {
                  const href = `/skills/${skill.id}`
                  const busy = Boolean(busyById[skill.id])
                  return (
                    <tr
                      key={skill.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{skill.display_name || skill.name || `Skill ${skill.id}`}</Link>
                      </td>
                      <td>
                        <p className="muted">{skill.name || '-'}</p>
                      </td>
                      <td>{skill.status || '-'}</td>
                      <td>{skill.latest_version || '-'}</td>
                      <td>{skill.binding_count ?? 0}</td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          {skill.is_git_read_only ? (
                            <span className="icon-button" aria-label="Git-based skill is read-only" title="Git-based skill is read-only">
                              <i className="fa-solid fa-lock" />
                            </span>
                          ) : (
                            <button
                              type="button"
                              className="icon-button icon-button-danger"
                              aria-label="Delete skill"
                              title="Delete skill"
                              disabled={busy}
                              onClick={() => handleDelete(skill.id)}
                            >
                              <ActionIcon name="trash" />
                            </button>
                          )}
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
