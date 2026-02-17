import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getSkillEdit, updateSkill } from '../lib/studioApi'

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

function parseJsonArray(raw, label) {
  if (!String(raw || '').trim()) {
    return []
  }
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON array.`)
  }
  return parsed
}

export default function SkillEditPage() {
  const navigate = useNavigate()
  const { skillId } = useParams()
  const parsedSkillId = useMemo(() => parseId(skillId), [skillId])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    displayName: '',
    description: '',
    status: 'active',
    newVersion: '',
    sourceRef: '',
    newSkillMd: '',
    existingFilesText: '[]',
    extraFilesText: '[]',
  })

  useEffect(() => {
    if (!parsedSkillId) {
      return
    }
    let cancelled = false
    getSkillEdit(parsedSkillId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        const skill = payload?.skill && typeof payload.skill === 'object' ? payload.skill : {}
        const nonSkillFiles = Array.isArray(payload?.latest_non_skill_files) ? payload.latest_non_skill_files : []
        const existingFiles = nonSkillFiles.map((entry) => ({
          original_path: entry.path,
          path: entry.path,
          delete: false,
        }))
        setForm({
          displayName: String(skill.display_name || ''),
          description: String(skill.description || ''),
          status: String(skill.status || 'active'),
          newVersion: '',
          sourceRef: String(skill.source_ref || ''),
          newSkillMd: String(payload?.latest_skill_md || ''),
          existingFilesText: JSON.stringify(existingFiles, null, 2),
          extraFilesText: '[]',
        })
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load skill edit metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedSkillId])
  const invalidId = parsedSkillId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid skill id.' : state.error

  const statusOptions = Array.isArray(state.payload?.skill_status_options) ? state.payload.skill_status_options : []

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedSkillId) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updateSkill(parsedSkillId, {
        displayName: form.displayName,
        description: form.description,
        status: form.status,
        newVersion: form.newVersion,
        sourceRef: form.sourceRef,
        newSkillMd: form.newSkillMd,
        existingFiles: parseJsonArray(form.existingFilesText, 'Existing files draft'),
        extraFiles: parseJsonArray(form.extraFilesText, 'Extra files draft'),
      })
      navigate(`/skills/${parsedSkillId}`)
    } catch (error) {
      setActionError(errorMessage(error, error instanceof Error ? error.message : 'Failed to update skill.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit skill">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Edit Skill</h2>
            <p>Update metadata and publish new immutable versions.</p>
          </div>
          <div className="table-actions">
            {parsedSkillId ? <Link to={`/skills/${parsedSkillId}`} className="btn-link btn-secondary">Back to Skill</Link> : null}
            <Link to="/skills" className="btn-link btn-secondary">All Skills</Link>
          </div>
        </div>
        {loading ? <p>Loading skill...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!loading && !error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
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
              <span>New version (required for file changes)</span>
              <input
                type="text"
                value={form.newVersion}
                onChange={(event) => setForm((current) => ({ ...current, newVersion: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Source ref (optional)</span>
              <input
                type="text"
                value={form.sourceRef}
                onChange={(event) => setForm((current) => ({ ...current, sourceRef: event.target.value }))}
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
              <span>SKILL.md draft</span>
              <textarea
                value={form.newSkillMd}
                onChange={(event) => setForm((current) => ({ ...current, newSkillMd: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Existing files draft JSON</span>
              <textarea
                value={form.existingFilesText}
                onChange={(event) => setForm((current) => ({ ...current, existingFilesText: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Extra files draft JSON</span>
              <textarea
                value={form.extraFilesText}
                onChange={(event) => setForm((current) => ({ ...current, extraFilesText: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy}>Save Skill</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}
