import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import {
  getSettingsIntegrations,
  updateSettingsIntegrationsChroma,
  updateSettingsIntegrationsConfluence,
  updateSettingsIntegrationsGit,
  updateSettingsIntegrationsGithub,
  updateSettingsIntegrationsGoogleCloud,
  updateSettingsIntegrationsGoogleWorkspace,
  updateSettingsIntegrationsHuggingface,
  updateSettingsIntegrationsJira,
} from '../lib/studioApi'

const SECTION_IDS = [
  'git',
  'github',
  'jira',
  'confluence',
  'google_cloud',
  'google_workspace',
  'huggingface',
  'chroma',
]

function normalizeSection(raw) {
  const normalized = String(raw || '').trim().toLowerCase()
  if (!normalized || normalized === 'git') {
    return 'git'
  }
  if (normalized === 'google-cloud') {
    return 'google_cloud'
  }
  if (normalized === 'google-workspace') {
    return 'google_workspace'
  }
  if (SECTION_IDS.includes(normalized)) {
    return normalized
  }
  return 'git'
}

function routeSectionPath(sectionId) {
  if (sectionId === 'git') {
    return '/settings/integrations'
  }
  if (sectionId === 'google_cloud') {
    return '/settings/integrations/google-cloud'
  }
  if (sectionId === 'google_workspace') {
    return '/settings/integrations/google-workspace'
  }
  return `/settings/integrations/${sectionId}`
}

function sectionLabel(sectionId) {
  if (sectionId === 'google_cloud') {
    return 'Google Cloud'
  }
  if (sectionId === 'google_workspace') {
    return 'Google Workspace'
  }
  if (sectionId === 'huggingface') {
    return 'Hugging Face'
  }
  if (sectionId === 'chroma') {
    return 'ChromaDB'
  }
  return sectionId.charAt(0).toUpperCase() + sectionId.slice(1)
}

function asBool(value) {
  return String(value || '').trim().toLowerCase() === 'true'
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

export default function SettingsIntegrationsPage() {
  const { section } = useParams()
  const activeSection = useMemo(() => normalizeSection(section), [section])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [actionInfo, setActionInfo] = useState('')
  const [busy, setBusy] = useState(false)

  const [gitForm, setGitForm] = useState({ gitconfigContent: '' })
  const [githubForm, setGithubForm] = useState({ pat: '', repo: '', clearSshKey: false })
  const [jiraForm, setJiraForm] = useState({ apiKey: '', email: '', site: '', projectKey: '', board: '' })
  const [confluenceForm, setConfluenceForm] = useState({ apiKey: '', email: '', site: '', space: '' })
  const [googleCloudForm, setGoogleCloudForm] = useState({ serviceAccountJson: '', projectId: '', mcpEnabled: true })
  const [googleWorkspaceForm, setGoogleWorkspaceForm] = useState({ serviceAccountJson: '', delegatedUserEmail: '', mcpEnabled: false })
  const [huggingfaceToken, setHuggingfaceToken] = useState('')
  const [chromaForm, setChromaForm] = useState({ host: '', port: '', ssl: false })

  const [githubRepoOptions, setGithubRepoOptions] = useState([])
  const [jiraProjectOptions, setJiraProjectOptions] = useState([])
  const [jiraBoardOptions, setJiraBoardOptions] = useState([])
  const [confluenceSpaceOptions, setConfluenceSpaceOptions] = useState([])

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getSettingsIntegrations({ section: activeSection })
      setState({ loading: false, payload, error: '' })

      setGitForm({
        gitconfigContent: String(payload?.gitconfig_content || ''),
      })

      setGithubForm({
        pat: String(payload?.github_settings?.pat || ''),
        repo: String(payload?.github_settings?.repo || ''),
        clearSshKey: false,
      })

      setJiraForm({
        apiKey: String(payload?.jira_settings?.api_key || ''),
        email: String(payload?.jira_settings?.email || ''),
        site: String(payload?.jira_settings?.site || ''),
        projectKey: String(payload?.jira_settings?.project_key || ''),
        board: String(payload?.jira_settings?.board || ''),
      })

      setConfluenceForm({
        apiKey: String(payload?.confluence_settings?.api_key || ''),
        email: String(payload?.confluence_settings?.email || ''),
        site: String(payload?.confluence_settings?.site || ''),
        space: String(payload?.confluence_settings?.space || ''),
      })

      setGoogleCloudForm({
        serviceAccountJson: String(payload?.google_cloud_settings?.service_account_json || ''),
        projectId: String(payload?.google_cloud_settings?.google_cloud_project_id || ''),
        mcpEnabled: asBool(payload?.google_cloud_settings?.google_cloud_mcp_enabled || 'true'),
      })

      setGoogleWorkspaceForm({
        serviceAccountJson: String(payload?.google_workspace_settings?.service_account_json || ''),
        delegatedUserEmail: String(payload?.google_workspace_settings?.workspace_delegated_user_email || ''),
        mcpEnabled: asBool(payload?.google_workspace_settings?.google_workspace_mcp_enabled || 'false'),
      })

      setHuggingfaceToken(String(payload?.vllm_local_settings?.huggingface?.token || ''))

      setChromaForm({
        host: String(payload?.chroma_settings?.host || ''),
        port: String(payload?.chroma_settings?.port || ''),
        ssl: asBool(payload?.chroma_settings?.ssl || 'false'),
      })

      setGithubRepoOptions(Array.isArray(payload?.github_repo_options) ? payload.github_repo_options : [])
      setJiraProjectOptions(Array.isArray(payload?.jira_project_options) ? payload.jira_project_options : [])
      setJiraBoardOptions(Array.isArray(payload?.jira_board_options) ? payload.jira_board_options : [])
      setConfluenceSpaceOptions(Array.isArray(payload?.confluence_space_options) ? payload.confluence_space_options : [])
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load integration settings.'),
      }))
    }
  }, [activeSection])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function save(action, successMessage) {
    setActionError('')
    setActionInfo('')
    setBusy(true)
    try {
      const response = await action()
      if (Array.isArray(response?.github_repo_options)) {
        setGithubRepoOptions(response.github_repo_options)
      }
      if (Array.isArray(response?.jira_project_options)) {
        setJiraProjectOptions(response.jira_project_options)
      }
      if (Array.isArray(response?.jira_board_options)) {
        setJiraBoardOptions(response.jira_board_options)
      }
      if (Array.isArray(response?.confluence_space_options)) {
        setConfluenceSpaceOptions(response.confluence_space_options)
      }
      if (response?.normalized_hint) {
        setActionInfo(String(response.normalized_hint))
      } else {
        setActionInfo(successMessage)
      }
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update integration settings.'))
    } finally {
      setBusy(false)
    }
  }

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const integrationSections = Array.isArray(payload?.integration_sections) && payload.integration_sections.length > 0
    ? payload.integration_sections
    : SECTION_IDS.map((id) => ({ id, label: sectionLabel(id) }))

  return (
    <section className="stack" aria-label="Settings integrations">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Settings Integrations</h2>
            <p>Native React replacement for `/settings/integrations/*` configuration and validation controls.</p>
          </div>
          <div className="table-actions">
            <Link to="/settings/core" className="btn-link btn-secondary">Core</Link>
            <Link to="/settings/provider" className="btn-link btn-secondary">Provider</Link>
            <Link to="/settings/runtime" className="btn-link btn-secondary">Runtime</Link>
            <Link to="/settings/chat" className="btn-link btn-secondary">Chat</Link>
          </div>
        </div>
        <div className="toolbar">
          <div className="toolbar-group">
            {integrationSections.map((item) => {
              const itemId = normalizeSection(item?.id)
              const active = itemId === activeSection
              return (
                <Link
                  key={itemId}
                  to={routeSectionPath(itemId)}
                  className={active ? 'btn-link' : 'btn-link btn-secondary'}
                >
                  {item?.label || sectionLabel(itemId)}
                </Link>
              )
            })}
          </div>
        </div>
        {state.loading ? <p>Loading integration settings...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
      </article>

      {!state.loading && !state.error && activeSection === 'git' ? (
        <article className="card">
          <h2>Git</h2>
          <div className="form-grid">
            <label className="field field-span">
              <span>{payload?.gitconfig_path || '~/.gitconfig'}</span>
              <textarea
                value={gitForm.gitconfigContent}
                rows={16}
                onChange={(event) => setGitForm({ gitconfigContent: event.target.value })}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsGit({ gitconfigContent: gitForm.gitconfigContent }),
                  'Git config updated.',
                )}
              >
                Save Git Config
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error && activeSection === 'github' ? (
        <article className="card">
          <h2>GitHub</h2>
          <div className="form-grid">
            <label className="field">
              <span>PAT</span>
              <input
                type="password"
                value={githubForm.pat}
                onChange={(event) => setGithubForm((current) => ({ ...current, pat: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Repository</span>
              <select
                value={githubForm.repo}
                onChange={(event) => setGithubForm((current) => ({ ...current, repo: event.target.value }))}
              >
                <option value="">Select repository</option>
                {githubRepoOptions.map((repo) => (
                  <option key={repo} value={repo}>{repo}</option>
                ))}
              </select>
            </label>
            <label className="checkbox-item">
              <input
                type="checkbox"
                checked={githubForm.clearSshKey}
                onChange={(event) => setGithubForm((current) => ({ ...current, clearSshKey: event.target.checked }))}
              />
              <span>Remove saved SSH key</span>
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link btn-secondary"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsGithub({
                    pat: githubForm.pat,
                    repo: githubForm.repo,
                    clearSshKey: githubForm.clearSshKey,
                    action: 'refresh',
                  }),
                  'GitHub repositories refreshed.',
                )}
              >
                Refresh Repositories
              </button>
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsGithub({
                    pat: githubForm.pat,
                    repo: githubForm.repo,
                    clearSshKey: githubForm.clearSshKey,
                  }),
                  'GitHub settings updated.',
                )}
              >
                Save GitHub
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error && activeSection === 'jira' ? (
        <article className="card">
          <h2>Jira</h2>
          <div className="form-grid">
            <label className="field"><span>API key</span><input type="password" value={jiraForm.apiKey} onChange={(event) => setJiraForm((current) => ({ ...current, apiKey: event.target.value }))} /></label>
            <label className="field"><span>Email</span><input type="email" value={jiraForm.email} onChange={(event) => setJiraForm((current) => ({ ...current, email: event.target.value }))} /></label>
            <label className="field"><span>Site</span><input type="text" value={jiraForm.site} onChange={(event) => setJiraForm((current) => ({ ...current, site: event.target.value }))} /></label>
            <label className="field">
              <span>Project key</span>
              <select value={jiraForm.projectKey} onChange={(event) => setJiraForm((current) => ({ ...current, projectKey: event.target.value }))}>
                <option value="">Select project</option>
                {jiraProjectOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label || item.value}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Board</span>
              <select value={jiraForm.board} onChange={(event) => setJiraForm((current) => ({ ...current, board: event.target.value }))}>
                <option value="">Select board</option>
                {jiraBoardOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label || item.value}</option>
                ))}
              </select>
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link btn-secondary"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsJira({
                    apiKey: jiraForm.apiKey,
                    email: jiraForm.email,
                    site: jiraForm.site,
                    projectKey: jiraForm.projectKey,
                    board: jiraForm.board,
                    action: 'refresh',
                  }),
                  'Jira projects and boards refreshed.',
                )}
              >
                Refresh Jira
              </button>
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsJira({
                    apiKey: jiraForm.apiKey,
                    email: jiraForm.email,
                    site: jiraForm.site,
                    projectKey: jiraForm.projectKey,
                    board: jiraForm.board,
                  }),
                  'Jira settings updated.',
                )}
              >
                Save Jira
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error && activeSection === 'confluence' ? (
        <article className="card">
          <h2>Confluence</h2>
          <div className="form-grid">
            <label className="field"><span>API key</span><input type="password" value={confluenceForm.apiKey} onChange={(event) => setConfluenceForm((current) => ({ ...current, apiKey: event.target.value }))} /></label>
            <label className="field"><span>Email</span><input type="email" value={confluenceForm.email} onChange={(event) => setConfluenceForm((current) => ({ ...current, email: event.target.value }))} /></label>
            <label className="field"><span>Site</span><input type="text" value={confluenceForm.site} onChange={(event) => setConfluenceForm((current) => ({ ...current, site: event.target.value }))} /></label>
            <label className="field">
              <span>Space</span>
              <select value={confluenceForm.space} onChange={(event) => setConfluenceForm((current) => ({ ...current, space: event.target.value }))}>
                <option value="">Select space</option>
                {confluenceSpaceOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label || item.value}</option>
                ))}
              </select>
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link btn-secondary"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsConfluence({
                    apiKey: confluenceForm.apiKey,
                    email: confluenceForm.email,
                    site: confluenceForm.site,
                    space: confluenceForm.space,
                    action: 'refresh',
                  }),
                  'Confluence spaces refreshed.',
                )}
              >
                Refresh Confluence
              </button>
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsConfluence({
                    apiKey: confluenceForm.apiKey,
                    email: confluenceForm.email,
                    site: confluenceForm.site,
                    space: confluenceForm.space,
                  }),
                  'Confluence settings updated.',
                )}
              >
                Save Confluence
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error && activeSection === 'google_cloud' ? (
        <article className="card">
          <h2>Google Cloud</h2>
          <div className="form-grid">
            <label className="field field-span"><span>Service account JSON</span><textarea value={googleCloudForm.serviceAccountJson} rows={10} onChange={(event) => setGoogleCloudForm((current) => ({ ...current, serviceAccountJson: event.target.value }))} /></label>
            <label className="field"><span>Project ID</span><input type="text" value={googleCloudForm.projectId} onChange={(event) => setGoogleCloudForm((current) => ({ ...current, projectId: event.target.value }))} /></label>
            <label className="checkbox-item"><input type="checkbox" checked={googleCloudForm.mcpEnabled} onChange={(event) => setGoogleCloudForm((current) => ({ ...current, mcpEnabled: event.target.checked }))} /><span>Enable Google Cloud MCP server</span></label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsGoogleCloud(googleCloudForm),
                  'Google Cloud settings updated.',
                )}
              >
                Save Google Cloud
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error && activeSection === 'google_workspace' ? (
        <article className="card">
          <h2>Google Workspace</h2>
          <div className="form-grid">
            <label className="field field-span"><span>Service account JSON</span><textarea value={googleWorkspaceForm.serviceAccountJson} rows={10} onChange={(event) => setGoogleWorkspaceForm((current) => ({ ...current, serviceAccountJson: event.target.value }))} /></label>
            <label className="field"><span>Delegated user email</span><input type="email" value={googleWorkspaceForm.delegatedUserEmail} onChange={(event) => setGoogleWorkspaceForm((current) => ({ ...current, delegatedUserEmail: event.target.value }))} /></label>
            <label className="checkbox-item"><input type="checkbox" checked={googleWorkspaceForm.mcpEnabled} onChange={(event) => setGoogleWorkspaceForm((current) => ({ ...current, mcpEnabled: event.target.checked }))} /><span>Enable Google Workspace MCP server</span></label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsGoogleWorkspace(googleWorkspaceForm),
                  'Google Workspace settings updated.',
                )}
              >
                Save Google Workspace
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error && activeSection === 'huggingface' ? (
        <article className="card">
          <h2>Hugging Face</h2>
          <div className="form-grid">
            <label className="field"><span>Token</span><input type="password" value={huggingfaceToken} onChange={(event) => setHuggingfaceToken(event.target.value)} /></label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsHuggingface({ token: huggingfaceToken }),
                  'Hugging Face settings updated.',
                )}
              >
                Save Hugging Face
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error && activeSection === 'chroma' ? (
        <article className="card">
          <h2>ChromaDB</h2>
          <div className="form-grid">
            <label className="field"><span>Host</span><input type="text" value={chromaForm.host} onChange={(event) => setChromaForm((current) => ({ ...current, host: event.target.value }))} /></label>
            <label className="field"><span>Port</span><input type="number" value={chromaForm.port} onChange={(event) => setChromaForm((current) => ({ ...current, port: event.target.value }))} /></label>
            <label className="checkbox-item"><input type="checkbox" checked={chromaForm.ssl} onChange={(event) => setChromaForm((current) => ({ ...current, ssl: event.target.checked }))} /><span>Enable SSL</span></label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsIntegrationsChroma(chromaForm),
                  'ChromaDB settings updated.',
                )}
              >
                Save ChromaDB
              </button>
            </div>
          </div>
        </article>
      ) : null}
    </section>
  )
}
