import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { resolveApiUrl } from '../config/runtime'
import { HttpError } from '../lib/httpClient'
import { getSkill } from '../lib/studioApi'

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

export default function SkillDetailPage() {
  const { skillId } = useParams()
  const parsedSkillId = useMemo(() => parseId(skillId), [skillId])
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedVersion = String(searchParams.get('version') || '')

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (!parsedSkillId) {
      return
    }
    let cancelled = false
    getSkill(parsedSkillId, { version: selectedVersion })
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load skill.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedSkillId, selectedVersion])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const skill = payload?.skill && typeof payload.skill === 'object' ? payload.skill : null
  const versions = Array.isArray(payload?.versions) ? payload.versions : []
  const preview = payload?.preview && typeof payload.preview === 'object' ? payload.preview : null
  const attachedAgents = Array.isArray(payload?.attached_agents) ? payload.attached_agents : []
  const invalidId = parsedSkillId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid skill id.' : state.error

  const exportHref = skill
    ? resolveApiUrl(`/skills/${skill.id}/export${selectedVersion ? `?version=${encodeURIComponent(selectedVersion)}` : ''}`)
    : ''

  return (
    <section className="stack" aria-label="Skill detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{skill ? skill.display_name || skill.name : 'Skill'}</h2>
            <p>{skill?.description || 'Native React replacement for `/skills/:skillId` version/detail view.'}</p>
          </div>
          <div className="table-actions">
            {skill ? <Link to={`/skills/${skill.id}/edit`} className="btn-link">Edit</Link> : null}
            {skill ? <a href={exportHref} className="btn-link btn-secondary">Export</a> : null}
            <Link to="/skills" className="btn-link btn-secondary">All Skills</Link>
          </div>
        </div>
        {loading ? <p>Loading skill...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {skill ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Status</dt>
                <dd>{skill.status || '-'}</dd>
              </div>
              <div>
                <dt>Latest version</dt>
                <dd>{skill.latest_version || '-'}</dd>
              </div>
              <div>
                <dt>Bindings</dt>
                <dd>{skill.binding_count ?? 0}</dd>
              </div>
            </dl>
            <label className="field">
              <span>Version</span>
              <select
                value={selectedVersion}
                onChange={(event) => {
                  const next = event.target.value
                  const updated = new URLSearchParams(searchParams)
                  if (next) {
                    updated.set('version', next)
                  } else {
                    updated.delete('version')
                  }
                  setSearchParams(updated)
                }}
              >
                <option value="">Latest</option>
                {versions.map((version) => (
                  <option key={version.id} value={version.version}>{version.version}</option>
                ))}
              </select>
            </label>
            {preview ? <pre>{JSON.stringify(preview, null, 2)}</pre> : null}
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Attached agents</h2>
        {attachedAgents.length === 0 ? <p>No agent bindings.</p> : (
          <ul>
            {attachedAgents.map((agent) => (
              <li key={agent.id}>
                <Link to={`/agents/${agent.id}`}>{agent.name || `Agent ${agent.id}`}</Link>
              </li>
            ))}
          </ul>
        )}
      </article>
    </section>
  )
}
