import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import TableListEmptyState from '../components/TableListEmptyState'
import TwoColumnListShell from '../components/TwoColumnListShell'
import { resolveApiUrl } from '../config/runtime'
import { HttpError } from '../lib/httpClient'
import { useFlashState } from '../lib/flashMessages'
import { getSkill, getSkillEdit, updateSkill } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const SKILL_SECTION_OPTIONS = [
  { id: 'metadata', label: 'Metadata', icon: 'fa-solid fa-circle-info' },
  { id: 'files', label: 'Files', icon: 'fa-solid fa-folder-open' },
  { id: 'agents', label: 'Attached Agents', icon: 'fa-solid fa-robot' },
]

function normalizeSection(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (SKILL_SECTION_OPTIONS.some((option) => option.id === normalized)) {
    return normalized
  }
  return 'metadata'
}

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

function formatBytes(value) {
  const size = Number.parseInt(String(value || ''), 10)
  if (!Number.isFinite(size) || size < 1) {
    return '-'
  }
  if (size < 1024) {
    return `${size} B`
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function buildEditForm(editPayload) {
  const skill = editPayload?.skill && typeof editPayload.skill === 'object' ? editPayload.skill : {}
  const existingFiles = Array.isArray(editPayload?.latest_non_skill_files)
    ? editPayload.latest_non_skill_files.map((entry) => ({
      originalPath: String(entry.path || ''),
      path: String(entry.path || ''),
      delete: false,
      sizeBytes: entry.size_bytes,
      isBinary: Boolean(entry.is_binary),
    }))
    : []
  const statusOptions = Array.isArray(editPayload?.skill_status_options)
    ? editPayload.skill_status_options
    : []
  const defaultStatus = statusOptions[0]?.value || 'active'
  return {
    displayName: String(skill.display_name || ''),
    description: String(skill.description || ''),
    status: String(skill.status || defaultStatus),
    sourceRef: String(skill.source_ref || ''),
    newVersion: '',
    newSkillMd: String(editPayload?.latest_skill_md || ''),
    existingFiles,
    extraFiles: [],
  }
}

function sectionTitle(section) {
  if (section === 'files') {
    return 'Skill Files'
  }
  if (section === 'agents') {
    return 'Attached Agents'
  }
  return 'Skill Metadata'
}

export default function SkillDetailPage() {
  const navigate = useNavigate()
  const { skillId } = useParams()
  const parsedSkillId = useMemo(() => parseId(skillId), [skillId])
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedVersion = String(searchParams.get('version') || '')
  const activeSection = normalizeSection(searchParams.get('section'))
  const [state, setState] = useState({
    loading: true,
    payload: null,
    editPayload: null,
    error: '',
    editError: '',
  })
  const [, setActionError] = useFlashState('error')
  const [, setActionSuccess] = useFlashState('success')
  const [saving, setSaving] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)
  const [nextExtraFileId, setNextExtraFileId] = useState(1)
  const [form, setForm] = useState({
    displayName: '',
    description: '',
    status: 'active',
    sourceRef: '',
    newVersion: '',
    newSkillMd: '',
    existingFiles: [],
    extraFiles: [],
  })

  useEffect(() => {
    if (!parsedSkillId) {
      return
    }
    let cancelled = false
    setState((current) => ({ ...current, loading: true, error: '' }))
    Promise.allSettled([
      getSkill(parsedSkillId, { version: selectedVersion }),
      getSkillEdit(parsedSkillId),
    ])
      .then(([detailResult, editResult]) => {
        if (cancelled) {
          return
        }
        if (detailResult.status !== 'fulfilled') {
          setState({
            loading: false,
            payload: null,
            editPayload: null,
            error: errorMessage(detailResult.reason, 'Failed to load skill.'),
            editError: '',
          })
          return
        }
        let editPayload = null
        let editError = ''
        if (editResult.status === 'fulfilled') {
          editPayload = editResult.value
        } else if (!(editResult.reason instanceof HttpError && editResult.reason.status === 409)) {
          editError = errorMessage(editResult.reason, 'Failed to load skill editor data.')
        }
        if (!cancelled) {
          setState({
            loading: false,
            payload: detailResult.value,
            editPayload,
            error: '',
            editError,
          })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            loading: false,
            payload: null,
            editPayload: null,
            error: errorMessage(error, 'Failed to load skill.'),
            editError: '',
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedSkillId, reloadToken, selectedVersion])

  useEffect(() => {
    if (!state.editPayload) {
      return
    }
    const nextForm = buildEditForm(state.editPayload)
    setForm(nextForm)
    setNextExtraFileId(1)
  }, [state.editPayload])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const editPayload = state.editPayload && typeof state.editPayload === 'object' ? state.editPayload : null
  const skill = payload?.skill && typeof payload.skill === 'object' ? payload.skill : null
  const versions = Array.isArray(payload?.versions) ? payload.versions : []
  const preview = payload?.preview && typeof payload.preview === 'object' ? payload.preview : null
  const previewFiles = Array.isArray(preview?.files) ? preview.files : []
  const attachedAgents = Array.isArray(payload?.attached_agents) ? payload.attached_agents : []
  const skillIsGitReadOnly = Boolean(payload?.skill_is_git_read_only)
  const canEdit = Boolean(editPayload) && !skillIsGitReadOnly
  const statusOptions = Array.isArray(editPayload?.skill_status_options) ? editPayload.skill_status_options : []
  const maxUploadBytes = Number.parseInt(String(editPayload?.max_upload_bytes || ''), 10) || 0
  const invalidId = parsedSkillId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid skill id.' : state.error

  const sidebarItems = useMemo(
    () => SKILL_SECTION_OPTIONS.map((option) => {
      const nextSearchParams = new URLSearchParams(searchParams)
      nextSearchParams.set('section', option.id)
      const nextSearch = nextSearchParams.toString()
      const href = `/skills/${parsedSkillId || skillId}${nextSearch ? `?${nextSearch}` : ''}`
      return {
        id: option.id,
        label: option.label,
        icon: option.icon,
        to: href,
      }
    }),
    [parsedSkillId, searchParams, skillId],
  )

  const exportHref = skill
    ? resolveApiUrl(`/skills/${skill.id}/export${selectedVersion ? `?version=${encodeURIComponent(selectedVersion)}` : ''}`)
    : ''

  const selectedVersionValue = selectedVersion || ''
  const selectedVersionLabel = selectedVersion || (payload?.selected_version ? String(payload.selected_version) : 'latest')

  function updateFormField(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  function updateExistingFileField(originalPath, field, value) {
    setForm((current) => ({
      ...current,
      existingFiles: current.existingFiles.map((entry) => {
        if (entry.originalPath !== originalPath) {
          return entry
        }
        return { ...entry, [field]: value }
      }),
    }))
  }

  function addExtraFileRow() {
    setForm((current) => ({
      ...current,
      extraFiles: [
        ...current.extraFiles,
        { id: nextExtraFileId, path: '', content: '', sourceName: '' },
      ],
    }))
    setNextExtraFileId((current) => current + 1)
  }

  function removeExtraFileRow(id) {
    setForm((current) => ({
      ...current,
      extraFiles: current.extraFiles.filter((entry) => entry.id !== id),
    }))
  }

  function updateExtraFileField(id, field, value) {
    setForm((current) => ({
      ...current,
      extraFiles: current.extraFiles.map((entry) => {
        if (entry.id !== id) {
          return entry
        }
        return { ...entry, [field]: value }
      }),
    }))
  }

  async function handleAddPickedFiles(event) {
    const fileList = Array.from(event.target.files || [])
    if (fileList.length === 0) {
      return
    }
    setActionError('')
    const addedRows = []
    let nextId = nextExtraFileId
    for (const file of fileList) {
      if (maxUploadBytes > 0 && file.size > maxUploadBytes) {
        setActionError(`File '${file.name}' exceeds the ${(maxUploadBytes / (1024 * 1024)).toFixed(0)} MB limit.`)
        continue
      }
      try {
        const content = await file.text()
        addedRows.push({
          id: nextId,
          path: file.name,
          content,
          sourceName: file.name,
        })
        nextId += 1
      } catch (uploadError) {
        setActionError(errorMessage(uploadError, `Failed to read '${file.name}'.`))
      }
    }
    event.target.value = ''
    if (addedRows.length === 0) {
      return
    }
    setForm((current) => ({
      ...current,
      extraFiles: [...current.extraFiles, ...addedRows],
    }))
    setNextExtraFileId(nextId)
    setActionSuccess(`${addedRows.length} file draft${addedRows.length === 1 ? '' : 's'} added.`)
  }

  function handleAgentRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  async function handleSave() {
    if (!parsedSkillId || !canEdit || saving) {
      return
    }
    const displayName = String(form.displayName || '').trim()
    const description = String(form.description || '').trim()
    const status = String(form.status || '').trim()
    const sourceRef = String(form.sourceRef || '').trim()
    const newVersion = String(form.newVersion || '').trim()
    const newSkillMd = String(form.newSkillMd || '')

    if (!displayName) {
      setActionError('Display name is required.')
      return
    }
    if (!description) {
      setActionError('Description is required.')
      return
    }
    if (!status) {
      setActionError('Status is required.')
      return
    }

    const existingFiles = []
    for (const entry of form.existingFiles) {
      const targetPath = String(entry.path || '').trim()
      if (!entry.delete && !targetPath) {
        setActionError(`Target path is required for '${entry.originalPath}'.`)
        return
      }
      existingFiles.push({
        original_path: entry.originalPath,
        path: targetPath,
        delete: Boolean(entry.delete),
      })
    }

    const extraFiles = []
    const seenExtraPaths = new Set()
    for (const entry of form.extraFiles) {
      const path = String(entry.path || '').trim()
      const content = String(entry.content || '')
      if (!path && !content) {
        continue
      }
      if (!path) {
        setActionError('Each new file row must include a path.')
        return
      }
      if (seenExtraPaths.has(path)) {
        setActionError(`Duplicate new file path '${path}'.`)
        return
      }
      seenExtraPaths.add(path)
      extraFiles.push({ path, content })
    }

    setSaving(true)
    setActionError('')
    setActionSuccess('')
    try {
      await updateSkill(parsedSkillId, {
        displayName,
        description,
        status,
        newVersion,
        newSkillMd,
        existingFiles,
        extraFiles,
        sourceRef,
      })
      const nextSearchParams = new URLSearchParams(searchParams)
      if (newVersion) {
        nextSearchParams.set('version', newVersion)
      }
      if (!nextSearchParams.get('section')) {
        nextSearchParams.set('section', activeSection)
      }
      setSearchParams(nextSearchParams)
      setActionSuccess(newVersion ? `Published version ${newVersion}.` : 'Skill metadata updated.')
      setReloadToken((current) => current + 1)
    } catch (saveError) {
      setActionError(errorMessage(saveError, 'Failed to update skill.'))
    } finally {
      setSaving(false)
    }
  }

  function renderMetadataSection() {
    return (
      <>
        <p className="panel-header-copy">
          Manage skill metadata and draft the next published version from a structured form.
        </p>
        {skillIsGitReadOnly ? (
          <p className="muted">Git-based skills are read-only in Studio. Edit the source repository instead.</p>
        ) : null}
        {state.editError ? <p className="error-text">{state.editError}</p> : null}
        <div className="workflow-list-table-shell">
          <div className="table-wrap">
            <table className="data-table">
              <tbody>
                <tr>
                  <th scope="row">Name</th>
                  <td>{skill?.name || '-'}</td>
                </tr>
                <tr>
                  <th scope="row">Selected version</th>
                  <td>{selectedVersionLabel}</td>
                </tr>
                <tr>
                  <th scope="row">Latest version</th>
                  <td>{skill?.latest_version || '-'}</td>
                </tr>
                <tr>
                  <th scope="row">Status</th>
                  <td>{skill?.status || '-'}</td>
                </tr>
                <tr>
                  <th scope="row">Bindings</th>
                  <td>{skill?.binding_count ?? 0}</td>
                </tr>
                <tr>
                  <th scope="row">Files in selected version</th>
                  <td>{previewFiles.length}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <label className="field">
          <span>Version preview</span>
          <select
            value={selectedVersionValue}
            onChange={(event) => {
              const next = event.target.value
              const updated = new URLSearchParams(searchParams)
              updated.set('section', activeSection)
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
        {canEdit ? (
          <form
            className="form-grid"
            onSubmit={(event) => {
              event.preventDefault()
              handleSave()
            }}
          >
            <label className="field">
              <span>Display name</span>
              <input
                type="text"
                required
                value={form.displayName}
                onChange={(event) => updateFormField('displayName', event.target.value)}
              />
            </label>
            <label className="field">
              <span>Status</span>
              <select
                value={form.status}
                onChange={(event) => updateFormField('status', event.target.value)}
              >
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>New version</span>
              <input
                type="text"
                value={form.newVersion}
                onChange={(event) => updateFormField('newVersion', event.target.value)}
              />
            </label>
            <label className="field">
              <span>Source ref</span>
              <input
                type="text"
                value={form.sourceRef}
                onChange={(event) => updateFormField('sourceRef', event.target.value)}
              />
            </label>
            <label className="field field-span">
              <span>Description</span>
              <textarea
                required
                value={form.description}
                onChange={(event) => updateFormField('description', event.target.value)}
              />
            </label>
            <label className="field field-span">
              <span>SKILL.md draft</span>
              <textarea
                value={form.newSkillMd}
                onChange={(event) => updateFormField('newSkillMd', event.target.value)}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={saving}>Save changes</button>
            </div>
          </form>
        ) : null}
      </>
    )
  }

  function renderFilesSection() {
    const hasExistingFiles = form.existingFiles.length > 0
    return (
      <>
        <p className="panel-header-copy">
          Rename, remove, and add files in the next version draft. File changes require a new version value.
        </p>
        {skillIsGitReadOnly ? (
          <p className="muted">Git-based skills are read-only in Studio. Edit the source repository instead.</p>
        ) : null}
        {state.editError ? <p className="error-text">{state.editError}</p> : null}
        <section className="stack-sm" aria-label="Existing files">
          <h3>Existing files</h3>
          <div className="workflow-list-table-shell">
            {hasExistingFiles ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Original path</th>
                      <th>Target path</th>
                      <th>Size</th>
                      <th>Type</th>
                      <th>Delete</th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.existingFiles.map((entry) => (
                      <tr key={entry.originalPath}>
                        <td>{entry.originalPath}</td>
                        <td>
                          <input
                            type="text"
                            className="skill-file-path-input"
                            value={entry.path}
                            disabled={entry.delete || !canEdit}
                            onChange={(event) => updateExistingFileField(entry.originalPath, 'path', event.target.value)}
                          />
                        </td>
                        <td>{formatBytes(entry.sizeBytes)}</td>
                        <td>{entry.isBinary ? 'binary' : 'text'}</td>
                        <td>
                          <label className="skill-file-delete-toggle">
                            <input
                              type="checkbox"
                              checked={entry.delete}
                              disabled={!canEdit}
                              onChange={(event) => updateExistingFileField(entry.originalPath, 'delete', event.target.checked)}
                            />
                            <span>Delete</span>
                          </label>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <TableListEmptyState message="No existing files in the latest draft." />
            )}
          </div>
        </section>
        <section className="stack-sm" aria-label="New files">
          <h3>New files to add</h3>
          {canEdit ? (
            <div className="form-actions">
              <button type="button" className="btn-link btn-secondary" onClick={addExtraFileRow}>
                Add file row
              </button>
              <label className="btn-link btn-secondary">
                Add from local files
                <input
                  type="file"
                  multiple
                  onChange={handleAddPickedFiles}
                  className="skill-files-input"
                />
              </label>
              {maxUploadBytes > 0 ? (
                <p className="table-note">
                  Max file size: {(maxUploadBytes / (1024 * 1024)).toFixed(0)} MB
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="workflow-list-table-shell">
            {form.extraFiles.length > 0 ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Path</th>
                      <th>Content</th>
                      <th className="table-actions-cell">Remove</th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.extraFiles.map((entry) => (
                      <tr key={entry.id}>
                        <td>
                          <label className="field">
                            <span>Path</span>
                            <input
                              type="text"
                              aria-label="New file path"
                              value={entry.path}
                              disabled={!canEdit}
                              onChange={(event) => updateExtraFileField(entry.id, 'path', event.target.value)}
                            />
                          </label>
                        </td>
                        <td>
                          <label className="field">
                            <span>Content</span>
                            <textarea
                              aria-label="New file content"
                              value={entry.content}
                              disabled={!canEdit}
                              onChange={(event) => updateExtraFileField(entry.id, 'content', event.target.value)}
                            />
                          </label>
                        </td>
                        <td className="table-actions-cell">
                          <div className="table-actions">
                            <button
                              type="button"
                              className="icon-button icon-button-danger"
                              aria-label="Remove file draft"
                              title="Remove file draft"
                              disabled={!canEdit}
                              onClick={() => removeExtraFileRow(entry.id)}
                            >
                              <ActionIcon name="trash" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <TableListEmptyState message="No new file drafts added yet." />
            )}
          </div>
        </section>
        {canEdit ? (
          <form
            className="form-actions"
            onSubmit={(event) => {
              event.preventDefault()
              handleSave()
            }}
          >
            <button type="submit" className="btn-link" disabled={saving}>Save changes</button>
          </form>
        ) : null}
      </>
    )
  }

  function renderAgentsSection() {
    return (
      <>
        <p className="panel-header-copy">Agents currently bound to this skill.</p>
        <div className="workflow-list-table-shell">
          {attachedAgents.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Status</th>
                    <th>Description</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {attachedAgents.map((agent) => {
                    const href = `/agents/${agent.id}`
                    return (
                      <tr
                        key={agent.id}
                        className="table-row-link"
                        data-href={href}
                        onClick={(event) => handleAgentRowClick(event, href)}
                      >
                        <td>
                          <Link to={href}>{agent.name || `Agent ${agent.id}`}</Link>
                        </td>
                        <td>{agent.status || '-'}</td>
                        <td>{agent.description || '-'}</td>
                        <td>{agent.updated_at || '-'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <TableListEmptyState message="No agent bindings." />
          )}
        </div>
      </>
    )
  }

  function renderSectionContent() {
    if (activeSection === 'agents') {
      return renderAgentsSection()
    }
    if (activeSection === 'files') {
      return renderFilesSection()
    }
    return renderMetadataSection()
  }

  return (
    <TwoColumnListShell
      ariaLabel="Skill detail"
      className="provider-fixed-page"
      sidebarAriaLabel="Skill sections"
      sidebarTitle="Skill"
      sidebarItems={sidebarItems}
      activeSidebarId={activeSection}
      mainTitle={sectionTitle(activeSection)}
      mainActions={(
        <div className="pagination-bar-actions">
          <p className="panel-header-meta">{skill ? (skill.display_name || skill.name) : 'Skill'}</p>
          {canEdit && activeSection !== 'agents' ? (
            <button
              type="button"
              className="icon-button"
              aria-label="Save skill changes"
              title="Save skill changes"
              disabled={saving}
              onClick={handleSave}
            >
              <ActionIcon name="save" />
            </button>
          ) : null}
          {skill ? (
            <a href={exportHref} className="icon-button" aria-label="Export skill" title="Export skill">
              <i className="fa-solid fa-download" aria-hidden="true" />
            </a>
          ) : null}
          <Link to="/skills" className="icon-button" aria-label="All skills" title="All skills">
            <i className="fa-solid fa-list" aria-hidden="true" />
          </Link>
        </div>
      )}
    >
      {loading ? <p>Loading skill...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {!loading && !error ? renderSectionContent() : null}
    </TwoColumnListShell>
  )
}
