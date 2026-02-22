import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useSearchParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { renderChatMarkdown } from '../lib/chatMarkdown'
import {
  archiveChatThread,
  clearChatThread,
  createChatThread,
  getChatThread,
  getChatRuntime,
  sendChatTurn,
  updateChatThreadConfig,
} from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'
import PanelHeader from '../components/PanelHeader'
import PersistedDetails from '../components/PersistedDetails'

const CHAT_SIDE_COLLAPSED_KEY = 'llmctl-chat-side-collapsed'
const DETAILS_STORAGE_PREFIX = 'llmctl-ui-details:'
const CHAT_SESSION_CONTROLS_STORAGE_KEY = 'chat:session-controls'

function parseThreadId(value) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function readPersistedDetailsOpen(storageKey, defaultOpen = false) {
  const normalized = String(storageKey || '').trim()
  if (!normalized) {
    return Boolean(defaultOpen)
  }
  try {
    const raw = window.localStorage.getItem(`${DETAILS_STORAGE_PREFIX}${normalized}`)
    if (raw === '1') {
      return true
    }
    if (raw === '0') {
      return false
    }
  } catch {
    return Boolean(defaultOpen)
  }
  return Boolean(defaultOpen)
}

function threadSummaryFromThread(thread) {
  if (!thread || typeof thread !== 'object') {
    return null
  }
  return {
    id: thread.id,
    title: thread.title,
    status: thread.status,
    model_id: thread.model_id,
    model_name: thread.model_name,
    response_complexity: thread.response_complexity,
    response_complexity_label: thread.response_complexity_label,
    rag_collections: Array.isArray(thread.rag_collections) ? thread.rag_collections : [],
    mcp_servers: Array.isArray(thread.mcp_servers) ? thread.mcp_servers : [],
    last_activity_at: thread.last_activity_at,
    updated_at: thread.updated_at,
    created_at: thread.created_at,
  }
}

function buildSessionConfig(thread, defaults) {
  const defaultModelId = defaults && defaults.default_model_id != null ? String(defaults.default_model_id) : ''
  const defaultComplexity = String(defaults?.default_response_complexity || 'medium')
  return {
    modelId: thread?.model_id != null ? String(thread.model_id) : defaultModelId,
    responseComplexity: String(thread?.response_complexity || defaultComplexity || 'medium'),
    mcpServerIds: Array.isArray(thread?.mcp_servers)
      ? thread.mcp_servers
        .map((item) => Number(item?.id))
        .filter((value) => Number.isInteger(value) && value > 0)
      : [],
    ragCollections: Array.isArray(thread?.rag_collections)
      ? thread.rag_collections
        .map((item) => String(item || '').trim())
        .filter((value) => value)
      : [],
  }
}

function messageFromError(error, fallback) {
  let message = error instanceof HttpError ? error.message : fallback
  if (error instanceof HttpError && error.isAuthError) {
    message = `${message} Sign in to Studio if authentication is enabled.`
  }
  if (error instanceof HttpError && error.body && typeof error.body === 'object') {
    const reasonCode = String(error.body.reason_code || '').trim()
    if (reasonCode) {
      message = `${message} (${reasonCode})`
    }
  }
  return message
}

function toggleNumericValue(values, value) {
  if (values.includes(value)) {
    return values.filter((item) => item !== value)
  }
  return [...values, value]
}

function toggleStringValue(values, value) {
  if (values.includes(value)) {
    return values.filter((item) => item !== value)
  }
  return [...values, value]
}

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedThreadIdFromQuery = useMemo(
    () => parseThreadId(searchParams.get('thread_id')),
    [searchParams],
  )

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [, setChatError] = useFlashState('error')
  const [draftMessage, setDraftMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [pendingUserMessages, setPendingUserMessages] = useState([])
  const [showPendingAssistantBubble, setShowPendingAssistantBubble] = useState(false)
  const [creatingThread, setCreatingThread] = useState(false)
  const [archivingThreadId, setArchivingThreadId] = useState(null)
  const [clearingThread, setClearingThread] = useState(false)
  const [savingSession, setSavingSession] = useState(false)
  const [sessionDirty, setSessionDirty] = useState(false)
  const [sessionConfig, setSessionConfig] = useState({
    modelId: '',
    responseComplexity: 'medium',
    mcpServerIds: [],
    ragCollections: [],
  })
  const [isSessionControlsOpen, setIsSessionControlsOpen] = useState(() =>
    readPersistedDetailsOpen(CHAT_SESSION_CONTROLS_STORAGE_KEY, true),
  )
  const [isSideCollapsed, setIsSideCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(CHAT_SIDE_COLLAPSED_KEY) === '1'
    } catch {
      return false
    }
  })

  const messageInputRef = useRef(null)
  const messageLogRef = useRef(null)
  const skipNextRuntimeLoadRef = useRef(false)
  const pendingMessageCounterRef = useRef(0)

  useEffect(() => {
    if (skipNextRuntimeLoadRef.current) {
      skipNextRuntimeLoadRef.current = false
      return undefined
    }

    let cancelled = false
    setState((current) => ({
      ...current,
      loading: true,
      error: '',
    }))

    async function loadRuntime() {
      try {
        const payload = await getChatRuntime({
          threadId: selectedThreadIdFromQuery || '',
        })
        if (cancelled) {
          return
        }
        setState({ loading: false, payload, error: '' })
        setChatError('')

        const selectedThread = payload && typeof payload === 'object' ? payload.selected_thread : null
        const defaultSettings = payload && typeof payload === 'object' ? payload.chat_default_settings : null
        setSessionConfig(buildSessionConfig(selectedThread, defaultSettings))
        setSessionDirty(false)

        const resolvedSelectedThreadId = parseThreadId(payload?.selected_thread_id)
        if (resolvedSelectedThreadId && resolvedSelectedThreadId !== selectedThreadIdFromQuery) {
          skipNextRuntimeLoadRef.current = true
          setSearchParams({ thread_id: String(resolvedSelectedThreadId) }, { replace: true })
        } else if (!resolvedSelectedThreadId && selectedThreadIdFromQuery) {
          skipNextRuntimeLoadRef.current = true
          setSearchParams({}, { replace: true })
        }
      } catch (error) {
        if (!cancelled) {
          setState({
            loading: false,
            payload: null,
            error: messageFromError(error, 'Failed to load chat runtime.'),
          })
        }
      }
    }

    loadRuntime()
    return () => {
      cancelled = true
    }
  }, [refreshVersion, selectedThreadIdFromQuery, setChatError, setSearchParams])

  useEffect(() => {
    try {
      window.localStorage.setItem(CHAT_SIDE_COLLAPSED_KEY, isSideCollapsed ? '1' : '0')
    } catch {
      return
    }
  }, [isSideCollapsed])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const threads = useMemo(
    () => (payload && Array.isArray(payload.threads) ? payload.threads : []),
    [payload],
  )
  const models = useMemo(
    () => (payload && Array.isArray(payload.models) ? payload.models : []),
    [payload],
  )
  const mcpServers = useMemo(
    () => (payload && Array.isArray(payload.mcp_servers) ? payload.mcp_servers : []),
    [payload],
  )
  const ragCollections = useMemo(
    () => (payload && Array.isArray(payload.rag_collections) ? payload.rag_collections : []),
    [payload],
  )
  const selectedThread = payload && payload.selected_thread && typeof payload.selected_thread === 'object'
    ? payload.selected_thread
    : null
  const selectedThreadId = selectedThread && selectedThread.id != null ? Number(selectedThread.id) : null
  const selectedThreadMessages = useMemo(
    () => (Array.isArray(selectedThread?.messages) ? selectedThread.messages : []),
    [selectedThread?.messages],
  )
  const visibleMessages = useMemo(() => {
    const messages = [...selectedThreadMessages, ...pendingUserMessages]
    if (!showPendingAssistantBubble) {
      return messages
    }
    return [
      ...messages,
      {
        id: 'pending-assistant',
        role: 'assistant',
        content: 'Thinking...',
        pending: true,
      },
    ]
  }, [pendingUserMessages, selectedThreadMessages, showPendingAssistantBubble])

  useEffect(() => {
    setPendingUserMessages([])
    setShowPendingAssistantBubble(false)
  }, [selectedThreadId])

  const autosizeMessageInput = useCallback(() => {
    const input = messageInputRef.current
    if (!input) {
      return
    }
    const styles = window.getComputedStyle(input)
    const lineHeight = Number.parseFloat(styles.lineHeight) || 22
    const paddingTop = Number.parseFloat(styles.paddingTop) || 0
    const paddingBottom = Number.parseFloat(styles.paddingBottom) || 0
    const maxHeight = lineHeight * 4 + paddingTop + paddingBottom
    input.style.height = 'auto'
    if (input.scrollHeight > maxHeight) {
      input.style.height = `${maxHeight}px`
      input.style.overflowY = 'auto'
    } else {
      input.style.height = `${input.scrollHeight}px`
      input.style.overflowY = 'hidden'
    }
  }, [])

  useEffect(() => {
    autosizeMessageInput()
  }, [autosizeMessageInput, draftMessage])

  useEffect(() => {
    const log = messageLogRef.current
    if (!log) {
      return
    }
    log.scrollTop = log.scrollHeight
  }, [visibleMessages.length])

  function updateSelectedThread(nextThread) {
    if (!nextThread || typeof nextThread !== 'object') {
      return
    }
    const summary = threadSummaryFromThread(nextThread)
    setState((current) => {
      if (!current.payload || typeof current.payload !== 'object') {
        return current
      }
      const existingThreads = Array.isArray(current.payload.threads)
        ? [...current.payload.threads]
        : []
      const existingIndex = existingThreads.findIndex((item) => Number(item?.id) === Number(nextThread.id))
      if (summary) {
        if (existingIndex >= 0) {
          existingThreads[existingIndex] = summary
        } else {
          existingThreads.unshift(summary)
        }
      }
      return {
        ...current,
        payload: {
          ...current.payload,
          selected_thread_id: nextThread.id,
          selected_thread: nextThread,
          threads: existingThreads,
        },
      }
    })
  }

  async function handleCreateThread() {
    setCreatingThread(true)
    setChatError('')
    try {
      const response = await createChatThread()
      const thread = response && typeof response === 'object' ? response.thread : null
      const nextThreadId = parseThreadId(thread?.id)
      if (thread && typeof thread === 'object') {
        updateSelectedThread(thread)
        setSessionConfig(buildSessionConfig(thread, payload?.chat_default_settings || null))
        setSessionDirty(false)
      }
      if (nextThreadId) {
        skipNextRuntimeLoadRef.current = true
        setSearchParams({ thread_id: String(nextThreadId) })
      }
      if (!thread || typeof thread !== 'object') {
        setRefreshVersion((value) => value + 1)
      }
    } catch (error) {
      setChatError(messageFromError(error, 'Failed to create chat thread.'))
    } finally {
      setCreatingThread(false)
    }
  }

  async function handleArchiveThread(threadId) {
    if (!threadId) {
      return
    }
    if (!window.confirm('Remove this thread from the list?')) {
      return
    }
    setArchivingThreadId(threadId)
    setChatError('')
    try {
      await archiveChatThread(threadId)
      const fallbackThread = threads.find((item) => Number(item?.id) !== Number(threadId))
      const deletedSelectedThread = selectedThreadId && Number(selectedThreadId) === Number(threadId)
      setState((current) => {
        if (!current.payload || typeof current.payload !== 'object') {
          return current
        }
        const nextThreads = Array.isArray(current.payload.threads)
          ? current.payload.threads.filter((item) => Number(item?.id) !== Number(threadId))
          : []
        return {
          ...current,
          payload: {
            ...current.payload,
            threads: nextThreads,
            selected_thread_id: deletedSelectedThread ? null : current.payload.selected_thread_id,
            selected_thread: deletedSelectedThread ? null : current.payload.selected_thread,
          },
        }
      })

      if (selectedThreadId && Number(selectedThreadId) === Number(threadId)) {
        if (fallbackThread?.id) {
          const fallbackThreadId = Number(fallbackThread.id)
          let loadedFallback = false
          try {
            const fallbackPayload = await getChatThread(fallbackThreadId)
            if (fallbackPayload && typeof fallbackPayload === 'object') {
              updateSelectedThread(fallbackPayload)
              setSessionConfig(
                buildSessionConfig(fallbackPayload, payload?.chat_default_settings || null),
              )
              setSessionDirty(false)
              loadedFallback = true
            }
          } catch (error) {
            setChatError(messageFromError(error, 'Failed to load fallback thread.'))
            setRefreshVersion((value) => value + 1)
          }
          skipNextRuntimeLoadRef.current = loadedFallback
          setSearchParams({ thread_id: String(fallbackThread.id) })
        } else {
          setSessionConfig(buildSessionConfig(null, payload?.chat_default_settings || null))
          setSessionDirty(false)
          skipNextRuntimeLoadRef.current = true
          setSearchParams({})
        }
      }
    } catch (error) {
      setChatError(messageFromError(error, 'Failed to archive chat thread.'))
    } finally {
      setArchivingThreadId(null)
    }
  }

  async function handleClearThread() {
    if (!selectedThreadId) {
      return
    }
    if (!window.confirm('Clear this thread context and messages?')) {
      return
    }
    setClearingThread(true)
    setChatError('')
    try {
      const payloadResponse = await clearChatThread(selectedThreadId)
      const thread = payloadResponse && typeof payloadResponse === 'object' ? payloadResponse.thread : null
      if (thread && typeof thread === 'object') {
        updateSelectedThread(thread)
        setSessionConfig(buildSessionConfig(thread, payload?.chat_default_settings || null))
        setSessionDirty(false)
      } else {
        setRefreshVersion((value) => value + 1)
      }
    } catch (error) {
      setChatError(messageFromError(error, 'Failed to clear thread.'))
    } finally {
      setClearingThread(false)
    }
  }

  const saveSessionControls = useCallback(async () => {
    if (!selectedThreadId || !sessionDirty) {
      return true
    }
    setSavingSession(true)
    setChatError('')
    try {
      const response = await updateChatThreadConfig(selectedThreadId, {
        modelId: sessionConfig.modelId ? Number(sessionConfig.modelId) : null,
        responseComplexity: sessionConfig.responseComplexity,
        mcpServerIds: sessionConfig.mcpServerIds,
        ragCollections: sessionConfig.ragCollections,
      })
      if (!response || typeof response !== 'object' || !response.ok) {
        setChatError('Failed to apply session controls.')
        return false
      }
      if (response.thread && typeof response.thread === 'object') {
        updateSelectedThread(response.thread)
        setSessionConfig(buildSessionConfig(response.thread, payload?.chat_default_settings || null))
      }
      setSessionDirty(false)
      return true
    } catch (error) {
      setChatError(messageFromError(error, 'Failed to apply session controls.'))
      return false
    } finally {
      setSavingSession(false)
    }
  }, [payload?.chat_default_settings, selectedThreadId, sessionConfig, sessionDirty, setChatError])

  async function handleSubmit(event) {
    event.preventDefault()
    if (!selectedThreadId || state.loading) {
      return
    }
    const message = draftMessage.trim()
    if (!message) {
      setChatError('Message is required.')
      return
    }
    pendingMessageCounterRef.current += 1
    const optimisticMessageId = `pending-user-${pendingMessageCounterRef.current}`
    setPendingUserMessages((current) => [
      ...current,
      {
        id: optimisticMessageId,
        role: 'user',
        content: message,
      },
    ])
    setDraftMessage('')
    setSending(true)
    setShowPendingAssistantBubble(true)
    setChatError('')
    const controlsSynced = await saveSessionControls()
    if (!controlsSynced) {
      setPendingUserMessages((current) => current.filter((item) => item.id !== optimisticMessageId))
      setDraftMessage(message)
      setShowPendingAssistantBubble(false)
      setSending(false)
      return
    }
    try {
      const response = await sendChatTurn(selectedThreadId, message)
      setShowPendingAssistantBubble(false)
      setPendingUserMessages((current) => current.filter((item) => item.id !== optimisticMessageId))
      if (!response || typeof response !== 'object' || !response.ok) {
        setDraftMessage(message)
        setChatError('Chat request failed.')
        return
      }
      if (response.thread && typeof response.thread === 'object') {
        updateSelectedThread(response.thread)
      } else {
        setRefreshVersion((value) => value + 1)
      }
    } catch (error) {
      setPendingUserMessages((current) => current.filter((item) => item.id !== optimisticMessageId))
      setDraftMessage(message)
      setShowPendingAssistantBubble(false)
      setChatError(messageFromError(error, 'Chat request failed.'))
    } finally {
      setShowPendingAssistantBubble(false)
      setSending(false)
      if (messageInputRef.current) {
        messageInputRef.current.focus()
      }
    }
  }

  function handleThreadRowClick(event, threadId) {
    if (!threadId || state.loading || shouldIgnoreRowClick(event.target)) {
      return
    }
    skipNextRuntimeLoadRef.current = false
    setSearchParams({ thread_id: String(threadId) })
  }

  function handleMessageKeyDown(event) {
    if (event.isComposing || sending || state.loading || !selectedThreadId) {
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      const form = event.currentTarget.form
      if (form) {
        form.requestSubmit()
      }
    }
  }

  return (
    <section className={`chat-live-layout${isSideCollapsed ? ' chat-side-collapsed' : ''}`} id="chat-live-layout">
      <aside className="chat-panel chat-side-panel">
        <PanelHeader
          title="Threads"
          actions={(
            <>
              <button
                type="button"
                className="icon-button"
                aria-label="Create thread"
                title="Create thread"
                onClick={handleCreateThread}
                disabled={creatingThread || state.loading}
              >
                <i className="fa-solid fa-plus" />
              </button>
              <Link className="icon-button" to="/chat/activity" aria-label="Chat activity" title="Chat activity">
                <i className="fa-solid fa-timeline" />
              </Link>
            </>
          )}
        />

        {selectedThread ? (
          <PersistedDetails
            className="chat-session-drawer"
            storageKey={CHAT_SESSION_CONTROLS_STORAGE_KEY}
            defaultOpen
            onToggle={(event) => {
              setIsSessionControlsOpen(Boolean(event.currentTarget?.open))
            }}
          >
            <summary>
              <span className="chat-session-title">controls</span>
              <span className="chat-session-summary">
                <button
                  type="button"
                  className="icon-button chat-session-summary-action"
                  aria-label={isSessionControlsOpen ? 'Save session controls' : 'Expand session controls'}
                  title={isSessionControlsOpen ? 'Save session controls' : 'Expand session controls'}
                  disabled={savingSession || (isSessionControlsOpen && !sessionDirty)}
                  onClick={async (event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    const summary = event.currentTarget.closest('summary')
                    const drawer = summary?.parentElement
                    if (!summary || !drawer) {
                      return
                    }
                    if (!drawer.open) {
                      summary.click()
                      return
                    }
                    await saveSessionControls()
                  }}
                >
                  <i className={`fa-solid ${isSessionControlsOpen ? 'fa-floppy-disk' : 'fa-angle-down'}`} />
                </button>
              </span>
            </summary>
            <div className="chat-session-content">
              <form
                className="chat-session-controls"
                id="chat-session-controls-form"
                onSubmit={async (event) => {
                  event.preventDefault()
                  await saveSessionControls()
                }}
              >
                <div className="chat-session-form-grid">
                  <label className="chat-control">
                    model
                    <select
                      name="model_id"
                      value={sessionConfig.modelId}
                      onChange={(event) => {
                        setSessionConfig((current) => ({ ...current, modelId: event.target.value }))
                        setSessionDirty(true)
                      }}
                    >
                      <option value="">Default model</option>
                      {models.map((model) => (
                        <option key={`chat-model-${model.id}`} value={model.id}>
                          {model.name} ({model.provider})
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="chat-control">
                    complexity
                    <select
                      name="response_complexity"
                      value={sessionConfig.responseComplexity}
                      onChange={(event) => {
                        setSessionConfig((current) => ({
                          ...current,
                          responseComplexity: event.target.value,
                        }))
                        setSessionDirty(true)
                      }}
                    >
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="extra_high">Extra High</option>
                    </select>
                  </label>
                </div>

                <div className="chat-session-groups">
                  <PersistedDetails
                    className="chat-picker chat-picker-group"
                    storageKey="chat:session-collections"
                  >
                    <summary>
                      <span className="chat-picker-summary">
                        <i className="fa-solid fa-database" />
                        <span>Collections</span>
                      </span>
                    </summary>
                    {payload?.rag_health?.state === 'configured_healthy' && ragCollections.length > 0 ? (
                      <div className="chat-checklist">
                        {ragCollections.map((collection) => {
                          const collectionId = String(collection?.id || '').trim()
                          if (!collectionId) {
                            return null
                          }
                          const checked = sessionConfig.ragCollections.includes(collectionId)
                          return (
                            <label key={`chat-rag-${collectionId || collection?.name}`}>
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => {
                                  setSessionConfig((current) => ({
                                    ...current,
                                    ragCollections: toggleStringValue(current.ragCollections, collectionId),
                                  }))
                                  setSessionDirty(true)
                                }}
                              />
                              <span>{collection.name}</span>
                            </label>
                          )
                        })}
                      </div>
                    ) : (
                      <p className="muted chat-picker-empty">
                        RAG state: {String(payload?.rag_health?.state || 'unconfigured')}
                        {payload?.rag_health?.error ? ` (${payload.rag_health.error})` : ''}
                      </p>
                    )}
                  </PersistedDetails>

                  <PersistedDetails
                    className="chat-picker chat-picker-group"
                    storageKey="chat:session-mcp-servers"
                  >
                    <summary>
                      <span className="chat-picker-summary">
                        <i className="fa-solid fa-plug" />
                        <span>MCP Servers</span>
                      </span>
                    </summary>
                    <div className="chat-checklist">
                      {mcpServers.map((mcp) => {
                        const mcpId = Number(mcp?.id)
                        if (!Number.isInteger(mcpId) || mcpId <= 0) {
                          return null
                        }
                        const checked = sessionConfig.mcpServerIds.includes(mcpId)
                        return (
                          <label key={`chat-mcp-${mcp.id}`}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                setSessionConfig((current) => ({
                                  ...current,
                                  mcpServerIds: toggleNumericValue(current.mcpServerIds, mcpId),
                                }))
                                setSessionDirty(true)
                              }}
                            />
                            <span>{mcp.name}</span>
                          </label>
                        )
                      })}
                    </div>
                  </PersistedDetails>
                </div>

                <div className="chat-session-actions">
                  <p className="chat-session-dirty" aria-live="polite">
                    {sessionDirty ? 'Unsaved changes' : 'Session is saved'}
                  </p>
                </div>
              </form>
            </div>
          </PersistedDetails>
        ) : null}

        {!state.loading && !state.error && threads.length > 0 ? (
          <div className="chat-thread-list-shell">
            <div className="chat-thread-list">
              {threads.map((thread) => {
                const threadId = parseThreadId(thread?.id)
                const isSelected = threadId && selectedThreadId && threadId === Number(selectedThreadId)
                return (
                  <div
                    key={`chat-thread-row-${thread.id}`}
                    className={`chat-thread-row table-row-link${isSelected ? ' chat-thread-row-selected' : ''}`}
                    data-href={threadId ? `/chat?thread_id=${threadId}` : undefined}
                    onClick={(event) => handleThreadRowClick(event, threadId)}
                  >
                    <p className="chat-thread-title">{thread.title || `Thread ${thread.id}`}</p>
                    <button
                      type="button"
                      className="icon-button icon-button-danger"
                      aria-label="Delete thread"
                      onClick={() => handleArchiveThread(threadId)}
                      disabled={archivingThreadId === threadId || state.loading}
                    >
                      <i className="fa-solid fa-trash" />
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}
        {!state.loading && !state.error && threads.length === 0 ? (
          <p className="muted chat-thread-empty">No chat threads yet.</p>
        ) : null}
      </aside>

      <article className="chat-panel">
        <PanelHeader
          title={selectedThread?.title || 'Live Chat'}
          actions={(
            <>
              <button
                type="button"
                className="icon-button"
                aria-label={isSideCollapsed ? 'Expand side panel' : 'Collapse side panel'}
                title={isSideCollapsed ? 'Expand side panel' : 'Collapse side panel'}
                onClick={() => setIsSideCollapsed((value) => !value)}
              >
                <i className={`fa-solid ${isSideCollapsed ? 'fa-angles-right' : 'fa-angles-left'}`} />
              </button>
              {selectedThread ? (
                <>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Clear thread"
                    title="Clear thread"
                    onClick={handleClearThread}
                    disabled={clearingThread || state.loading}
                  >
                    <i className="fa-solid fa-eraser" />
                  </button>
                  <button
                    id="chat-send-btn"
                    type="submit"
                    form="chat-turn-form"
                    className="icon-button icon-button-primary"
                    aria-label="Send message"
                    title="Send message"
                    disabled={sending || savingSession || state.loading}
                  >
                    <i className="fa-solid fa-paper-plane" />
                  </button>
                </>
              ) : null}
            </>
          )}
        />

        {state.loading ? <p className="muted chat-loading-state">Loading chat runtime...</p> : null}
        {state.error ? <p className="error-text chat-loading-state">{state.error}</p> : null}

        {!state.loading && !state.error && selectedThread ? (
          <>
            {selectedThread.compaction_summary_text ? (
              <PersistedDetails className="chat-compaction" storageKey="chat:compaction-summary">
                <summary>compaction summary</summary>
                <pre>{selectedThread.compaction_summary_text}</pre>
              </PersistedDetails>
            ) : null}

            <div className="chat-message-log" id="chat-message-log" ref={messageLogRef}>
              {visibleMessages.length > 0
                ? visibleMessages.map((item) => {
                  const role = String(item?.role || 'assistant').toLowerCase()
                  const isPending = Boolean(item?.pending)
                  return (
                    <div
                      key={`chat-message-${item.id || `${role}-${item.created_at}`}`}
                      className={`chat-message ${role === 'user' ? 'chat-message-user' : 'chat-message-assistant'}${isPending ? ' chat-message-pending' : ''}`}
                    >
                      {isPending ? (
                        <p className="chat-message-content chat-message-thinking">{item.content || 'Thinking...'}</p>
                      ) : (
                        <div
                          className="chat-message-content markdown-content"
                          dangerouslySetInnerHTML={{ __html: renderChatMarkdown(item.content || '') }}
                        />
                      )}
                    </div>
                  )
                })
                : <p className="muted">No messages in this thread yet.</p>}
            </div>

            <form id="chat-turn-form" className="chat-input-form" onSubmit={handleSubmit}>
              <textarea
                id="chat-message"
                name="message"
                rows="1"
                className="chat-input-textarea"
                placeholder="Send a message..."
                value={draftMessage}
                onChange={(event) => setDraftMessage(event.target.value)}
                onKeyDown={handleMessageKeyDown}
                disabled={sending || savingSession || state.loading}
                ref={messageInputRef}
              />
            </form>
          </>
        ) : null}

        {!state.loading && !state.error && !selectedThread ? (
          <div className="chat-empty">
            <p>Create or select a thread to start chatting.</p>
          </div>
        ) : null}
      </article>
    </section>
  )
}
