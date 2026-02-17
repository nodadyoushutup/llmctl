import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { useParams } from 'react-router-dom'
import SettingsInnerSidebar from '../components/SettingsInnerSidebar'
import { HttpError } from '../lib/httpClient'
import {
  getSettingsRuntime,
  updateSettingsRuntimeChat,
  updateSettingsRuntimeInstructions,
  updateSettingsRuntimeNodeExecutor,
  updateSettingsRuntimeRag,
} from '../lib/studioApi'

const SECTION_IDS = ['node', 'rag', 'chat']

function normalizeSection(raw) {
  const normalized = String(raw || '').trim().toLowerCase()
  if (!normalized || normalized === 'node') {
    return 'node'
  }
  if (normalized === 'rag' || normalized === 'chat') {
    return normalized
  }
  return 'node'
}

function routeSectionPath(sectionId) {
  if (sectionId === 'node') {
    return '/settings/runtime'
  }
  return `/settings/runtime/${sectionId}`
}

function sectionLabel(sectionId) {
  if (sectionId === 'rag') {
    return 'RAG Runtime'
  }
  if (sectionId === 'chat') {
    return 'Chat Runtime'
  }
  return 'Node Runtime'
}

function sectionIcon(sectionId) {
  if (sectionId === 'node') {
    return 'fa-solid fa-diagram-project'
  }
  if (sectionId === 'rag') {
    return 'fa-solid fa-database'
  }
  if (sectionId === 'chat') {
    return 'fa-solid fa-comments'
  }
  return 'fa-solid fa-circle-info'
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

function asBool(value) {
  return String(value || '').trim().toLowerCase() === 'true'
}

export default function SettingsRuntimePage() {
  const { section } = useParams()
  const activeSection = useMemo(() => normalizeSection(section), [section])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [actionInfo, setActionInfo] = useFlashState('success')
  const [busy, setBusy] = useState(false)

  const [nodeExecutorForm, setNodeExecutorForm] = useState({
    provider: 'kubernetes',
    workspaceIdentityKey: '',
    dispatchTimeoutSeconds: '',
    executionTimeoutSeconds: '',
    logCollectionTimeoutSeconds: '',
    cancelGraceTimeoutSeconds: '',
    cancelForceKillEnabled: false,
    k8sKubeconfig: '',
    k8sKubeconfigClear: false,
    k8sNamespace: '',
    k8sImage: '',
    k8sServiceAccount: '',
    k8sGpuLimit: '',
    k8sJobTtlSeconds: '',
    k8sImagePullSecretsJson: '',
    k8sInCluster: false,
  })
  const [instructionFlags, setInstructionFlags] = useState({})

  const [ragForm, setRagForm] = useState({
    dbProvider: '',
    embedProvider: '',
    chatProvider: '',
    openaiEmbedModel: '',
    geminiEmbedModel: '',
    openaiChatModel: '',
    geminiChatModel: '',
    chatTemperature: '',
    chatResponseStyle: '',
    chatTopK: '',
    chatMaxHistory: '',
    chatMaxContextChars: '',
    chatSnippetChars: '',
    chatContextBudgetTokens: '',
    indexParallelWorkers: '',
    embedParallelRequests: '',
  })

  const [chatRuntimeForm, setChatRuntimeForm] = useState({
    historyBudgetPercent: '',
    ragBudgetPercent: '',
    mcpBudgetPercent: '',
    compactionTriggerPercent: '',
    compactionTargetPercent: '',
    preserveRecentTurns: '',
    ragTopK: '',
    defaultContextWindowTokens: '',
    maxCompactionSummaryChars: '',
  })

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getSettingsRuntime({ section: activeSection })
      setState({ loading: false, payload, error: '' })

      const nodeExecutor = payload?.node_executor_settings && typeof payload.node_executor_settings === 'object'
        ? payload.node_executor_settings
        : {}
      setNodeExecutorForm({
        provider: String(nodeExecutor.provider || 'kubernetes'),
        workspaceIdentityKey: String(nodeExecutor.workspace_identity_key || ''),
        dispatchTimeoutSeconds: String(nodeExecutor.dispatch_timeout_seconds || ''),
        executionTimeoutSeconds: String(nodeExecutor.execution_timeout_seconds || ''),
        logCollectionTimeoutSeconds: String(nodeExecutor.log_collection_timeout_seconds || ''),
        cancelGraceTimeoutSeconds: String(nodeExecutor.cancel_grace_timeout_seconds || ''),
        cancelForceKillEnabled: asBool(nodeExecutor.cancel_force_kill_enabled),
        k8sKubeconfig: String(nodeExecutor.k8s_kubeconfig || ''),
        k8sKubeconfigClear: false,
        k8sNamespace: String(nodeExecutor.k8s_namespace || ''),
        k8sImage: String(nodeExecutor.k8s_image || ''),
        k8sServiceAccount: String(nodeExecutor.k8s_service_account || ''),
        k8sGpuLimit: String(nodeExecutor.k8s_gpu_limit || ''),
        k8sJobTtlSeconds: String(nodeExecutor.k8s_job_ttl_seconds || ''),
        k8sImagePullSecretsJson: String(nodeExecutor.k8s_image_pull_secrets_json || ''),
        k8sInCluster: asBool(nodeExecutor.k8s_in_cluster),
      })

      const flags = {}
      const flagRows = Array.isArray(payload?.instruction_runtime_flags)
        ? payload.instruction_runtime_flags
        : []
      flagRows.forEach((row) => {
        if (row?.native_key) {
          flags[row.native_key] = Boolean(row.native_enabled)
        }
        if (row?.fallback_key) {
          flags[row.fallback_key] = Boolean(row.fallback_enabled)
        }
      })
      setInstructionFlags(flags)

      const ragSettings = payload?.rag_settings && typeof payload.rag_settings === 'object'
        ? payload.rag_settings
        : {}
      setRagForm({
        dbProvider: String(ragSettings.db_provider || ''),
        embedProvider: String(ragSettings.embed_provider || ''),
        chatProvider: String(ragSettings.chat_provider || ''),
        openaiEmbedModel: String(ragSettings.openai_embed_model || ''),
        geminiEmbedModel: String(ragSettings.gemini_embed_model || ''),
        openaiChatModel: String(ragSettings.openai_chat_model || ''),
        geminiChatModel: String(ragSettings.gemini_chat_model || ''),
        chatTemperature: String(ragSettings.chat_temperature || ''),
        chatResponseStyle: String(ragSettings.chat_response_style || ''),
        chatTopK: String(ragSettings.chat_top_k || ''),
        chatMaxHistory: String(ragSettings.chat_max_history || ''),
        chatMaxContextChars: String(ragSettings.chat_max_context_chars || ''),
        chatSnippetChars: String(ragSettings.chat_snippet_chars || ''),
        chatContextBudgetTokens: String(ragSettings.chat_context_budget_tokens || ''),
        indexParallelWorkers: String(ragSettings.index_parallel_workers || ''),
        embedParallelRequests: String(ragSettings.embed_parallel_requests || ''),
      })

      const chatRuntime = payload?.chat_runtime_settings && typeof payload.chat_runtime_settings === 'object'
        ? payload.chat_runtime_settings
        : {}
      setChatRuntimeForm({
        historyBudgetPercent: String(chatRuntime.history_budget_percent || ''),
        ragBudgetPercent: String(chatRuntime.rag_budget_percent || ''),
        mcpBudgetPercent: String(chatRuntime.mcp_budget_percent || ''),
        compactionTriggerPercent: String(chatRuntime.compaction_trigger_percent || ''),
        compactionTargetPercent: String(chatRuntime.compaction_target_percent || ''),
        preserveRecentTurns: String(chatRuntime.preserve_recent_turns || ''),
        ragTopK: String(chatRuntime.rag_top_k || ''),
        defaultContextWindowTokens: String(chatRuntime.default_context_window_tokens || ''),
        maxCompactionSummaryChars: String(chatRuntime.max_compaction_summary_chars || ''),
      })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load runtime settings.'),
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
      const result = await action()
      if (result?.warning) {
        setActionInfo(String(result.warning))
      } else {
        setActionInfo(successMessage)
      }
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update runtime settings.'))
    } finally {
      setBusy(false)
    }
  }

  function toggleInstructionFlag(flagKey) {
    setInstructionFlags((current) => ({
      ...current,
      [flagKey]: !current[flagKey],
    }))
  }

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const runtimeSections = Array.isArray(payload?.runtime_sections) && payload.runtime_sections.length > 0
    ? payload.runtime_sections
    : SECTION_IDS.map((id) => ({ id, label: sectionLabel(id) }))
  const runtimeSidebarItems = runtimeSections.map((item) => {
    const itemId = normalizeSection(item?.id)
    return {
      id: itemId,
      to: routeSectionPath(itemId),
      label: item?.label || sectionLabel(itemId),
      icon: sectionIcon(itemId),
    }
  })
  const instructionRows = Array.isArray(payload?.instruction_runtime_flags)
    ? payload.instruction_runtime_flags
    : []

  return (
    <section className="stack" aria-label="Settings runtime">
      <SettingsInnerSidebar
        title="Runtime Sections"
        ariaLabel="Runtime sections"
        items={runtimeSidebarItems}
        activeId={activeSection}
      >
        <article className="card">
          {state.loading ? <p>Loading runtime settings...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {actionError ? <p className="error-text">{actionError}</p> : null}
          {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
          {!state.loading && !state.error ? (
            <>
            {activeSection === 'node' ? (
              <div className="stack-sm">
                <h3>Node executor</h3>
                <div className="form-grid">
                  <label className="field">
                    <span>Provider</span>
                    <select
                      value={nodeExecutorForm.provider}
                      onChange={(event) => setNodeExecutorForm((current) => ({ ...current, provider: event.target.value }))}
                    >
                      <option value="kubernetes">Kubernetes</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Workspace identity key</span>
                    <input
                      type="text"
                      value={nodeExecutorForm.workspaceIdentityKey}
                      onChange={(event) => setNodeExecutorForm((current) => ({ ...current, workspaceIdentityKey: event.target.value }))}
                    />
                  </label>
                  <label className="field"><span>Dispatch timeout seconds</span><input type="number" value={nodeExecutorForm.dispatchTimeoutSeconds} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, dispatchTimeoutSeconds: event.target.value }))} /></label>
                  <label className="field"><span>Execution timeout seconds</span><input type="number" value={nodeExecutorForm.executionTimeoutSeconds} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, executionTimeoutSeconds: event.target.value }))} /></label>
                  <label className="field"><span>Log collection timeout seconds</span><input type="number" value={nodeExecutorForm.logCollectionTimeoutSeconds} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, logCollectionTimeoutSeconds: event.target.value }))} /></label>
                  <label className="field"><span>Cancel grace timeout seconds</span><input type="number" value={nodeExecutorForm.cancelGraceTimeoutSeconds} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, cancelGraceTimeoutSeconds: event.target.value }))} /></label>
                  <label className="field"><span>Kubernetes namespace</span><input type="text" value={nodeExecutorForm.k8sNamespace} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sNamespace: event.target.value }))} /></label>
                  <label className="field"><span>Kubernetes image</span><input type="text" value={nodeExecutorForm.k8sImage} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sImage: event.target.value }))} /></label>
                  <label className="field"><span>Service account</span><input type="text" value={nodeExecutorForm.k8sServiceAccount} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sServiceAccount: event.target.value }))} /></label>
                  <label className="field"><span>GPU limit</span><input type="number" value={nodeExecutorForm.k8sGpuLimit} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sGpuLimit: event.target.value }))} /></label>
                  <label className="field"><span>Job TTL seconds</span><input type="number" value={nodeExecutorForm.k8sJobTtlSeconds} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sJobTtlSeconds: event.target.value }))} /></label>
                  <label className="field field-span"><span>Image pull secrets JSON</span><textarea value={nodeExecutorForm.k8sImagePullSecretsJson} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sImagePullSecretsJson: event.target.value }))} /></label>
                  <label className="field field-span"><span>Kubeconfig (optional)</span><textarea value={nodeExecutorForm.k8sKubeconfig} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sKubeconfig: event.target.value }))} /></label>
                  <label className="checkbox-item"><input type="checkbox" checked={nodeExecutorForm.k8sKubeconfigClear} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sKubeconfigClear: event.target.checked }))} /><span>Clear stored kubeconfig</span></label>
                  <label className="checkbox-item"><input type="checkbox" checked={nodeExecutorForm.cancelForceKillEnabled} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, cancelForceKillEnabled: event.target.checked }))} /><span>Enable cancel force kill</span></label>
                  <label className="checkbox-item"><input type="checkbox" checked={nodeExecutorForm.k8sInCluster} onChange={(event) => setNodeExecutorForm((current) => ({ ...current, k8sInCluster: event.target.checked }))} /><span>Use in-cluster credentials</span></label>
                  <div className="form-actions">
                    <button
                      type="button"
                      className="btn-link"
                      disabled={busy}
                      onClick={() => save(() => updateSettingsRuntimeNodeExecutor(nodeExecutorForm), 'Node executor runtime settings updated.')}
                    >
                      Save Node Executor
                    </button>
                  </div>
                </div>

                <h3>Instruction runtime flags</h3>
                <fieldset className="field">
                  <legend>Provider runtime behavior</legend>
                  <div className="checkbox-grid">
                    {instructionRows.map((row) => (
                      <div key={row.provider} className="subcard">
                        <p className="table-note">{row.label || row.provider}</p>
                        <label className="checkbox-item">
                          <input
                            type="checkbox"
                            checked={Boolean(instructionFlags[row.native_key])}
                            onChange={() => toggleInstructionFlag(row.native_key)}
                          />
                          <span>Native enabled</span>
                        </label>
                        <label className="checkbox-item">
                          <input
                            type="checkbox"
                            checked={Boolean(instructionFlags[row.fallback_key])}
                            onChange={() => toggleInstructionFlag(row.fallback_key)}
                          />
                          <span>Fallback enabled</span>
                        </label>
                      </div>
                    ))}
                  </div>
                </fieldset>
                <div className="form-actions">
                  <button
                    type="button"
                    className="btn-link btn-secondary"
                    disabled={busy}
                    onClick={() => save(
                      () => updateSettingsRuntimeInstructions(instructionFlags),
                      'Instruction runtime flags updated.',
                    )}
                  >
                    Save Instruction Flags
                  </button>
                </div>
              </div>
            ) : null}

            {activeSection === 'rag' ? (
              <div className="form-grid">
                <label className="field"><span>DB provider</span><select value={ragForm.dbProvider} onChange={(event) => setRagForm((current) => ({ ...current, dbProvider: event.target.value }))}>{(payload?.rag_db_provider_choices || []).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
                <label className="field"><span>Embed provider</span><select value={ragForm.embedProvider} onChange={(event) => setRagForm((current) => ({ ...current, embedProvider: event.target.value }))}>{(payload?.rag_model_provider_choices || []).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
                <label className="field"><span>Chat provider</span><select value={ragForm.chatProvider} onChange={(event) => setRagForm((current) => ({ ...current, chatProvider: event.target.value }))}>{(payload?.rag_model_provider_choices || []).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
                <label className="field"><span>OpenAI embed model</span><select value={ragForm.openaiEmbedModel} onChange={(event) => setRagForm((current) => ({ ...current, openaiEmbedModel: event.target.value }))}>{(payload?.rag_openai_embed_model_options || []).map((item) => <option key={item.value} value={item.value}>{item.label || item.value}</option>)}</select></label>
                <label className="field"><span>Gemini embed model</span><select value={ragForm.geminiEmbedModel} onChange={(event) => setRagForm((current) => ({ ...current, geminiEmbedModel: event.target.value }))}>{(payload?.rag_gemini_embed_model_options || []).map((item) => <option key={item.value} value={item.value}>{item.label || item.value}</option>)}</select></label>
                <label className="field"><span>OpenAI chat model</span><select value={ragForm.openaiChatModel} onChange={(event) => setRagForm((current) => ({ ...current, openaiChatModel: event.target.value }))}>{(payload?.rag_openai_chat_model_options || []).map((item) => <option key={item.value} value={item.value}>{item.label || item.value}</option>)}</select></label>
                <label className="field"><span>Gemini chat model</span><select value={ragForm.geminiChatModel} onChange={(event) => setRagForm((current) => ({ ...current, geminiChatModel: event.target.value }))}>{(payload?.rag_gemini_chat_model_options || []).map((item) => <option key={item.value} value={item.value}>{item.label || item.value}</option>)}</select></label>
                <label className="field"><span>Chat temperature</span><input type="number" step="0.1" value={ragForm.chatTemperature} onChange={(event) => setRagForm((current) => ({ ...current, chatTemperature: event.target.value }))} /></label>
                <label className="field"><span>Response style</span><select value={ragForm.chatResponseStyle} onChange={(event) => setRagForm((current) => ({ ...current, chatResponseStyle: event.target.value }))}>{(payload?.rag_chat_response_style_choices || []).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
                <label className="field"><span>Top K</span><input type="number" value={ragForm.chatTopK} onChange={(event) => setRagForm((current) => ({ ...current, chatTopK: event.target.value }))} /></label>
                <label className="field"><span>Max history</span><input type="number" value={ragForm.chatMaxHistory} onChange={(event) => setRagForm((current) => ({ ...current, chatMaxHistory: event.target.value }))} /></label>
                <label className="field"><span>Max context chars</span><input type="number" value={ragForm.chatMaxContextChars} onChange={(event) => setRagForm((current) => ({ ...current, chatMaxContextChars: event.target.value }))} /></label>
                <label className="field"><span>Snippet chars</span><input type="number" value={ragForm.chatSnippetChars} onChange={(event) => setRagForm((current) => ({ ...current, chatSnippetChars: event.target.value }))} /></label>
                <label className="field"><span>Context budget tokens</span><input type="number" value={ragForm.chatContextBudgetTokens} onChange={(event) => setRagForm((current) => ({ ...current, chatContextBudgetTokens: event.target.value }))} /></label>
                <label className="field"><span>Index parallel workers</span><input type="number" value={ragForm.indexParallelWorkers} onChange={(event) => setRagForm((current) => ({ ...current, indexParallelWorkers: event.target.value }))} /></label>
                <label className="field"><span>Embed parallel requests</span><input type="number" value={ragForm.embedParallelRequests} onChange={(event) => setRagForm((current) => ({ ...current, embedParallelRequests: event.target.value }))} /></label>
                <div className="form-actions">
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busy}
                    onClick={() => save(() => updateSettingsRuntimeRag(ragForm), 'RAG runtime settings updated.')}
                  >
                    Save RAG Runtime
                  </button>
                </div>
              </div>
            ) : null}

            {activeSection === 'chat' ? (
              <div className="form-grid">
                <label className="field"><span>History budget percent</span><input type="number" value={chatRuntimeForm.historyBudgetPercent} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, historyBudgetPercent: event.target.value }))} /></label>
                <label className="field"><span>RAG budget percent</span><input type="number" value={chatRuntimeForm.ragBudgetPercent} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, ragBudgetPercent: event.target.value }))} /></label>
                <label className="field"><span>MCP budget percent</span><input type="number" value={chatRuntimeForm.mcpBudgetPercent} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, mcpBudgetPercent: event.target.value }))} /></label>
                <label className="field"><span>Compaction trigger percent</span><input type="number" value={chatRuntimeForm.compactionTriggerPercent} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, compactionTriggerPercent: event.target.value }))} /></label>
                <label className="field"><span>Compaction target percent</span><input type="number" value={chatRuntimeForm.compactionTargetPercent} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, compactionTargetPercent: event.target.value }))} /></label>
                <label className="field"><span>Preserve recent turns</span><input type="number" value={chatRuntimeForm.preserveRecentTurns} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, preserveRecentTurns: event.target.value }))} /></label>
                <label className="field"><span>RAG top K</span><input type="number" value={chatRuntimeForm.ragTopK} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, ragTopK: event.target.value }))} /></label>
                <label className="field"><span>Default context window tokens</span><input type="number" value={chatRuntimeForm.defaultContextWindowTokens} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, defaultContextWindowTokens: event.target.value }))} /></label>
                <label className="field"><span>Max compaction summary chars</span><input type="number" value={chatRuntimeForm.maxCompactionSummaryChars} onChange={(event) => setChatRuntimeForm((current) => ({ ...current, maxCompactionSummaryChars: event.target.value }))} /></label>
                <div className="form-actions">
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busy}
                    onClick={() => save(
                      () => updateSettingsRuntimeChat({ ...chatRuntimeForm, returnTo: 'runtime' }),
                      'Chat runtime settings updated.',
                    )}
                  >
                    Save Chat Runtime
                  </button>
                </div>
              </div>
            ) : null}
            </>
          ) : null}
        </article>
      </SettingsInnerSidebar>
    </section>
  )
}
