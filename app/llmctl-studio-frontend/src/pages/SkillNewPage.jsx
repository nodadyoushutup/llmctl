import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { createSkill, getSkillMeta } from '../lib/studioApi'

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

function parseExtraFiles(raw) {
  if (!String(raw || '').trim()) {
    return []
  }
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed)) {
    throw new Error('Extra files must be a JSON array.')
  }
  return parsed
}

export default function SkillNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    name: '',
    displayName: '',
    description: '',
    version: '1.0.0',
    status: 'active',
    sourceRef: '',
    skillMd: '',
    extraFilesText: '[]',
  })

  useEffect(() => {
    let cancelled = false
    getSkillMeta()
      .then((payload) => {
        if (!cancelled) {
          const options = Array.isArray(payload?.skill_status_options) ? payload.skill_status_options : []
          setForm((current) => ({ ...current, status: current.status || options[0]?.value || 'active' }))
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load skill metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const statusOptions = Array.isArray(state.payload?.skill_status_options) ? state.payload.skill_status_options : []

  async function handleSubmit(event) {
    event.preventDefault()
    setActionError('')
    setBusy(true)
    try {
      const payload = await createSkill({
        ...form,
        extraFiles: parseExtraFiles(form.extraFilesText),
      })
      const skillId = payload?.skill_id || payload?.skill?.id
      if (skillId) {
        navigate(`/skills/${skillId}`)
      } else {
        navigate('/skills')
      }
    } catch (error) {
      setActionError(errorMessage(error, error instanceof Error ? error.message : 'Failed to create skill.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="New skill">
      <article className="card">
        <PanelHeader
          title="New Skill"
          titleTag="h2"
          actions={<Link to="/skills" className="btn-link btn-secondary">All Skills</Link>}
        />
        <p className="panel-header-copy">Create a new skill package and initial immutable version.</p>
        {state.loading ? <p>Loading skill options...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field">
              <span>Skill name (slug)</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Display name</span>
              <input
                type="text"
                required
                value={form.displayName}
                onChange={(event) => setForm((current) => ({ ...current, displayName: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Status</span>
              <select
                value={form.status}
                onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}
              >
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Version</span>
              <input
                type="text"
                value={form.version}
                onChange={(event) => setForm((current) => ({ ...current, version: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Description</span>
              <textarea
                required
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Source ref (optional)</span>
              <input
                type="text"
                value={form.sourceRef}
                onChange={(event) => setForm((current) => ({ ...current, sourceRef: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>SKILL.md</span>
              <textarea
                value={form.skillMd}
                onChange={(event) => setForm((current) => ({ ...current, skillMd: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>{'Extra files JSON array (`[{"path":"notes.md","content":"..."}]`)'}</span>
              <textarea
                value={form.extraFilesText}
                onChange={(event) => setForm((current) => ({ ...current, extraFilesText: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy}>Create Skill</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}
