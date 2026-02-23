import { useCallback, useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import HeaderPagination from '../components/HeaderPagination'
import PanelHeader from '../components/PanelHeader'
import TableListEmptyState from '../components/TableListEmptyState'
import { HttpError } from '../lib/httpClient'
import { deleteSkill, getSkills } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const SKILLS_PER_PAGE_OPTIONS = [10, 25, 50]

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function parsePerPage(value) {
  const parsed = parsePositiveInt(value, 25)
  return SKILLS_PER_PAGE_OPTIONS.includes(parsed) ? parsed : 25
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

export default function SkillsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePerPage(searchParams.get('per_page'))
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
  const totalRows = skills.length
  const totalPages = Math.max(1, Math.ceil(totalRows / perPage))
  const currentPage = Math.min(page, totalPages)
  const pageStart = (currentPage - 1) * perPage
  const visibleSkills = skills.slice(pageStart, pageStart + perPage)

  function updateParams(nextParams) {
    const updated = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(nextParams)) {
      if (value == null || value === '') {
        updated.delete(key)
      } else {
        updated.set(key, String(value))
      }
    }
    if (parsePositiveInt(updated.get('page'), 1) === 1) {
      updated.delete('page')
    }
    if (parsePerPage(updated.get('per_page')) === 25) {
      updated.delete('per_page')
    }
    setSearchParams(updated)
  }

  useEffect(() => {
    if (state.loading) {
      return
    }
    if (page === currentPage) {
      return
    }
    updateParams({ page: currentPage })
  }, [currentPage, page, searchParams, setSearchParams, state.loading])

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
    <section className="stack workflow-fixed-page" aria-label="Skills">
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title="Skills"
          actionsClassName="workflow-list-panel-header-actions"
          actions={(
            <div className="pagination-bar-actions">
              <HeaderPagination
                ariaLabel="Skills pages"
                canGoPrev={currentPage > 1}
                canGoNext={currentPage < totalPages}
                onPrev={() => updateParams({ page: currentPage - 1 })}
                onNext={() => updateParams({ page: currentPage + 1 })}
                currentPage={currentPage}
                totalPages={totalPages}
              />
              <div className="pagination-size">
                <label htmlFor="skills-per-page">Rows per page</label>
                <select
                  id="skills-per-page"
                  value={String(perPage)}
                  onChange={(event) => updateParams({ per_page: event.target.value, page: 1 })}
                >
                  {SKILLS_PER_PAGE_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
              <p className="panel-header-meta">{totalRows} skills</p>
              <Link to="/skills/import" className="icon-button" aria-label="Import skill" title="Import skill">
                <i className="fa-solid fa-file-import" aria-hidden="true" />
              </Link>
              <Link to="/skills/new" className="icon-button" aria-label="New skill" title="New skill">
                <ActionIcon name="plus" />
              </Link>
            </div>
          )}
        />
        <div className="panel-card-body workflow-fixed-panel-body">
          <p className="panel-header-copy">First-class skill packages assigned to Agents.</p>
          {state.loading ? <p>Loading skills...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {actionError ? <p className="error-text">{actionError}</p> : null}
          {!state.loading && !state.error ? (
            <div className="workflow-list-table-shell">
              {visibleSkills.length > 0 ? (
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
                      {visibleSkills.map((skill) => {
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
              ) : (
                <TableListEmptyState message="No skills created yet." />
              )}
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}
