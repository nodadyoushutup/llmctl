import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { getSkillImportMeta, importSkillBundle, previewSkillImport } from '../lib/studioApi'

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

export default function SkillImportPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [preview, setPreview] = useState(null)
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    sourceKind: 'upload',
    localPath: '',
    sourceRef: '',
    actor: '',
    gitUrl: '',
    bundlePayload: '',
  })

  useEffect(() => {
    let cancelled = false
    getSkillImportMeta()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load import metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handlePreview(event) {
    event.preventDefault()
    setActionError('')
    setBusy(true)
    try {
      const payload = await previewSkillImport(form)
      setPreview(payload?.preview || null)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to preview skill import.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleImport() {
    setActionError('')
    setBusy(true)
    try {
      const payload = await importSkillBundle(form)
      const skillId = payload?.skill_id
      if (skillId) {
        navigate(`/skills/${skillId}`)
      } else {
        navigate('/skills')
      }
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to import skill bundle.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Import skill">
      <article className="card">
        <PanelHeader
          title="Import Skill"
          titleTag="h2"
          actions={<Link to="/skills" className="btn-link btn-secondary">All Skills</Link>}
        />
        <p className="panel-header-copy">Import from bundle upload or local package directory.</p>
        {state.loading ? <p>Loading import metadata...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error ? (
          <form className="form-grid" onSubmit={handlePreview}>
            <label className="field">
              <span>Source kind</span>
              <select
                value={form.sourceKind}
                onChange={(event) => setForm((current) => ({ ...current, sourceKind: event.target.value }))}
              >
                <option value="upload">Bundle JSON</option>
                <option value="path">Local path</option>
                <option value="git">Git (deferred)</option>
              </select>
            </label>
            <label className="field">
              <span>Source ref (optional)</span>
              <input
                type="text"
                value={form.sourceRef}
                onChange={(event) => setForm((current) => ({ ...current, sourceRef: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Actor (optional)</span>
              <input
                type="text"
                value={form.actor}
                onChange={(event) => setForm((current) => ({ ...current, actor: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Git URL (optional)</span>
              <input
                type="text"
                value={form.gitUrl}
                onChange={(event) => setForm((current) => ({ ...current, gitUrl: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Local path (for source_kind=path)</span>
              <input
                type="text"
                value={form.localPath}
                onChange={(event) => setForm((current) => ({ ...current, localPath: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Bundle payload (for source_kind=upload)</span>
              <textarea
                value={form.bundlePayload}
                onChange={(event) => setForm((current) => ({ ...current, bundlePayload: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy}>Preview</button>
              <button type="button" className="btn-link btn-secondary" disabled={busy} onClick={handleImport}>Import</button>
            </div>
          </form>
        ) : null}
      </article>

      {preview ? (
        <article className="card">
          <PanelHeader title="Preview" titleTag="h2" />
          <pre>{JSON.stringify(preview, null, 2)}</pre>
        </article>
      ) : null}
    </section>
  )
}
