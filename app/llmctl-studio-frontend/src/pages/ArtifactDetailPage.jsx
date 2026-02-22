import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { getMemoryArtifact, getMilestoneArtifact, getNodeArtifact, getPlanArtifact } from '../lib/studioApi'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function normalizePanelId(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (DETAIL_PANELS.some((panel) => panel.id === normalized)) {
    return normalized
  }
  return 'data'
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

const ENTITY_CONFIG = {
  artifact: {
    label: 'artifact',
    listPath: '/artifacts/type/task',
  },
  plan: {
    label: 'plan',
    listPath: '/plans',
    fetchArtifact: getPlanArtifact,
  },
  milestone: {
    label: 'milestone',
    listPath: '/milestones',
    fetchArtifact: getMilestoneArtifact,
  },
  memory: {
    label: 'memory',
    listPath: '/memories',
    fetchArtifact: getMemoryArtifact,
  },
}

const DETAIL_PANELS = [
  { id: 'data', label: 'Data', icon: 'fa-solid fa-table-columns' },
  { id: 'metadata', label: 'Metadata', icon: 'fa-solid fa-circle-info' },
  { id: 'payload', label: 'Payload', icon: 'fa-solid fa-code' },
]

const DATA_LABELS = {
  id: 'ID',
  ref_id: 'Ref ID',
  name: 'Name',
  description: 'Description',
  status: 'Status',
  priority: 'Priority',
  owner: 'Owner',
  completed: 'Completed',
  completed_at: 'Completed At',
  created_at: 'Created',
  updated_at: 'Updated',
  progress_percent: 'Progress',
  start_date: 'Start Date',
  due_date: 'Due Date',
  latest_update: 'Latest Update',
  health: 'Health',
  stage_count: 'Stage Count',
  task_count: 'Task Count',
  action: 'Action',
  node_type: 'Node Type',
  output_action: 'Output Action',
  matched_routes: 'Matched Routes',
  evaluations_count: 'Evaluations',
  no_match: 'No Match',
  resolved_route_key: 'Resolved Route Key',
  resolved_route_path: 'Resolved Route Path',
  input_field_count: 'Input Field Count',
  output_field_count: 'Output Field Count',
  routing_field_count: 'Routing Field Count',
}

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function labelForField(key) {
  if (DATA_LABELS[key]) {
    return DATA_LABELS[key]
  }
  return String(key || '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function formatDataValue(value) {
  if (value == null || value === '') {
    return '-'
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }
  if (typeof value === 'number') {
    return String(value)
  }
  if (typeof value === 'string') {
    return value
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return '0 items'
    }
    if (value.every((item) => item == null || ['string', 'number', 'boolean'].includes(typeof item))) {
      return value.map((item) => formatDataValue(item)).join(', ')
    }
    return `${value.length} items`
  }
  if (isRecord(value)) {
    return `${Object.keys(value).length} fields`
  }
  return String(value)
}

function recordEntries(record, keys) {
  if (!isRecord(record)) {
    return []
  }
  return keys
    .filter((key) => Object.prototype.hasOwnProperty.call(record, key))
    .map((key) => ({
      key,
      label: labelForField(key),
      value: formatDataValue(record[key]),
    }))
}

function sectionFromRecord({ id, title, record, keys }) {
  const entries = recordEntries(record, keys)
  if (entries.length === 0) {
    return null
  }
  return { id, title, entries }
}

function countPlanTasks(stages) {
  if (!Array.isArray(stages)) {
    return 0
  }
  return stages.reduce((total, stage) => {
    if (!isRecord(stage) || !Array.isArray(stage.tasks)) {
      return total
    }
    return total + stage.tasks.length
  }, 0)
}

function toPrettyJson(value) {
  if (value == null) {
    return ''
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatArtifactContentText(value) {
  const text = String(value || '').trim()
  if (!text) {
    return ''
  }
  const looksLikeJsonObject = text.startsWith('{') && text.endsWith('}')
  const looksLikeJsonArray = text.startsWith('[') && text.endsWith(']')
  if (!looksLikeJsonObject && !looksLikeJsonArray) {
    return text
  }
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object') {
      return JSON.stringify(parsed, null, 2)
    }
  } catch {
    // Keep original text when content only looks like JSON.
  }
  return text
}

function buildPlanOutlineText(plan) {
  const lines = []
  const planName = String(plan?.name || '').trim()
  if (planName) {
    lines.push(`Plan: ${planName}`)
  }
  const planDescription = String(plan?.description || '').trim()
  if (planDescription) {
    lines.push(`Description: ${planDescription}`)
  }
  const stages = Array.isArray(plan?.stages) ? plan.stages : []
  if (stages.length === 0) {
    lines.push('No stages recorded.')
    return lines.join('\n')
  }
  lines.push('', 'Outline:')
  stages.forEach((stage, index) => {
    if (!isRecord(stage)) {
      return
    }
    const stageName = String(stage.name || '').trim() || `Stage ${index + 1}`
    lines.push(`${index + 1}. ${stageName}`)
    const tasks = Array.isArray(stage.tasks) ? stage.tasks : []
    if (tasks.length === 0) {
      lines.push('   - No tasks')
      return
    }
    tasks.forEach((task) => {
      if (!isRecord(task)) {
        return
      }
      const taskName = String(task.name || '').trim() || 'Untitled task'
      const isCompleted = String(task.completed_at || '').trim().length > 0
      lines.push(`   - [${isCompleted ? 'x' : ' '}] ${taskName}`)
    })
  })
  return lines.join('\n')
}

function buildMilestoneNotesText(milestone) {
  const lines = []
  const description = String(milestone?.description || '').trim()
  if (description) {
    lines.push(description)
  }
  const latestUpdate = String(milestone?.latest_update || '').trim()
  if (latestUpdate) {
    if (lines.length > 0) {
      lines.push('')
    }
    lines.push(`Latest update: ${latestUpdate}`)
  }
  const successCriteria = String(milestone?.success_criteria || '').trim()
  if (successCriteria) {
    if (lines.length > 0) {
      lines.push('')
    }
    lines.push('Success criteria:')
    lines.push(successCriteria)
  }
  const dependencies = milestone?.dependencies
  if (Array.isArray(dependencies) && dependencies.length > 0) {
    lines.push('', 'Dependencies:')
    dependencies.forEach((item) => {
      lines.push(`- ${String(item)}`)
    })
  } else if (typeof dependencies === 'string' && dependencies.trim()) {
    lines.push('', `Dependencies: ${dependencies.trim()}`)
  }
  return lines.join('\n')
}

function buildDecisionNotesText(payload, outputState) {
  const matchedRoutes = Array.isArray(payload?.matched_connector_ids)
    ? payload.matched_connector_ids.map((value) => String(value || '').trim()).filter(Boolean)
    : []
  const noMatch = Boolean(payload?.no_match)
  const resolvedRouteKey = String(payload?.resolved_route_key || outputState?.resolved_route_key || '').trim()
  const resolvedRoutePath = String(payload?.resolved_route_path || outputState?.resolved_route_path || '').trim()
  const evaluations = Array.isArray(payload?.evaluations) ? payload.evaluations : []

  const lines = [
    `Matched routes: ${matchedRoutes.length > 0 ? matchedRoutes.join(', ') : '-'}`,
    `No match: ${noMatch ? 'Yes' : 'No'}`,
    `Resolved route key: ${resolvedRouteKey || '-'}`,
    `Resolved route path: ${resolvedRoutePath || '-'}`,
    `Evaluations: ${evaluations.length}`,
  ]
  if (evaluations.length > 0) {
    lines.push('', 'Evaluation payload:')
    lines.push(toPrettyJson(evaluations))
  }
  return lines.join('\n')
}

function buildArtifactDataPresentation(artifact, dataSections) {
  if (!artifact) {
    return null
  }
  const payload = isRecord(artifact?.payload) ? artifact.payload : {}
  const outputState = isRecord(payload.output_state) ? payload.output_state : {}
  const artifactType = String(artifact?.artifact_type || '').trim().toLowerCase()

  const storedMemory = isRecord(payload.stored_memory)
    ? payload.stored_memory
    : (isRecord(outputState.stored_memory) ? outputState.stored_memory : null)
  const planRecord = isRecord(payload.plan) ? payload.plan : (isRecord(outputState.plan) ? outputState.plan : null)
  const milestoneRecord = isRecord(payload.milestone)
    ? payload.milestone
    : (isRecord(outputState.milestone) ? outputState.milestone : null)

  if (storedMemory) {
    return {
      title: 'Stored Memory',
      metadataEntries: recordEntries(storedMemory, ['id', 'created_at', 'updated_at']),
      contentTitle: 'description',
      contentText: formatArtifactContentText(storedMemory.description) || '-',
      secondarySections: dataSections.filter((section) => section.id !== 'memory-stored'),
    }
  }

  if (planRecord) {
    const stages = Array.isArray(planRecord.stages) ? planRecord.stages : []
    const planMetaRecord = {
      ...planRecord,
      stage_count: stages.length,
      task_count: countPlanTasks(stages),
    }
    return {
      title: 'Plan',
      metadataEntries: recordEntries(planMetaRecord, [
        'id',
        'completed_at',
        'stage_count',
        'task_count',
        'created_at',
        'updated_at',
      ]),
      contentTitle: 'plan outline',
      contentText: buildPlanOutlineText(planRecord) || '-',
      secondarySections: dataSections.filter((section) => section.id !== 'plan-data'),
    }
  }

  if (milestoneRecord) {
    return {
      title: 'Milestone',
      metadataEntries: recordEntries(milestoneRecord, [
        'id',
        'status',
        'priority',
        'owner',
        'completed',
        'progress_percent',
        'health',
        'start_date',
        'due_date',
        'created_at',
        'updated_at',
      ]),
      contentTitle: 'milestone notes',
      contentText: buildMilestoneNotesText(milestoneRecord) || '-',
      secondarySections: dataSections.filter((section) => section.id !== 'milestone-data'),
    }
  }

  if (artifactType === 'decision') {
    return {
      title: 'Decision',
      metadataEntries: recordEntries({
        no_match: payload.no_match,
        resolved_route_key: payload.resolved_route_key || outputState.resolved_route_key || '',
        resolved_route_path: payload.resolved_route_path || outputState.resolved_route_path || '',
        evaluations_count: Array.isArray(payload.evaluations) ? payload.evaluations.length : 0,
      }, ['no_match', 'resolved_route_key', 'resolved_route_path', 'evaluations_count']),
      contentTitle: 'decision analysis',
      contentText: buildDecisionNotesText(payload, outputState) || '-',
      secondarySections: dataSections.filter((section) => section.id !== 'decision-data'),
    }
  }

  const summarySection = dataSections.find((section) => section.id === 'artifact-summary') || dataSections[0] || null
  const primaryPayload = isRecord(outputState) && Object.keys(outputState).length > 0 ? outputState : payload
  return {
    title: 'Artifact',
    metadataEntries: summarySection ? summarySection.entries : [],
    contentTitle: 'payload summary',
    contentText: toPrettyJson(primaryPayload) || '-',
    secondarySections: summarySection
      ? dataSections.filter((section) => section.id !== summarySection.id)
      : [],
  }
}

function buildDataSections(artifact) {
  const payload = isRecord(artifact?.payload) ? artifact.payload : {}
  const outputState = isRecord(payload.output_state) ? payload.output_state : {}
  const inputContext = isRecord(payload.input_context) ? payload.input_context : {}
  const routingState = isRecord(payload.routing_state) ? payload.routing_state : {}
  const sections = []

  const memoryCandidate = isRecord(payload.stored_memory)
    ? payload.stored_memory
    : (isRecord(outputState.stored_memory) ? outputState.stored_memory : null)
  const retrievedMemories = Array.isArray(payload.retrieved_memories)
    ? payload.retrieved_memories.filter((row) => isRecord(row))
    : (Array.isArray(outputState.retrieved_memories)
      ? outputState.retrieved_memories.filter((row) => isRecord(row))
      : [])
  const planCandidate = isRecord(payload.plan)
    ? payload.plan
    : (isRecord(outputState.plan) ? outputState.plan : null)
  const milestoneCandidate = isRecord(payload.milestone)
    ? payload.milestone
    : (isRecord(outputState.milestone) ? outputState.milestone : null)

  if (memoryCandidate) {
    const memorySection = sectionFromRecord({
      id: 'memory-stored',
      title: 'Stored Memory',
      record: memoryCandidate,
      keys: ['id', 'description', 'created_at', 'updated_at'],
    })
    if (memorySection) {
      sections.push(memorySection)
    }
  }

  retrievedMemories.forEach((memoryRow, index) => {
    const retrievedSection = sectionFromRecord({
      id: `memory-retrieved-${index + 1}`,
      title: `Retrieved Memory ${index + 1}`,
      record: memoryRow,
      keys: ['id', 'description', 'created_at', 'updated_at'],
    })
    if (retrievedSection) {
      sections.push(retrievedSection)
    }
  })

  if (planCandidate) {
    const stages = Array.isArray(planCandidate.stages) ? planCandidate.stages : []
    const planSection = sectionFromRecord({
      id: 'plan-data',
      title: 'Plan',
      record: {
        ...planCandidate,
        stage_count: stages.length,
        task_count: countPlanTasks(stages),
      },
      keys: [
        'id',
        'name',
        'description',
        'completed_at',
        'stage_count',
        'task_count',
        'created_at',
        'updated_at',
      ],
    })
    if (planSection) {
      sections.push(planSection)
    }
  }

  if (milestoneCandidate) {
    const milestoneSection = sectionFromRecord({
      id: 'milestone-data',
      title: 'Milestone',
      record: milestoneCandidate,
      keys: [
        'id',
        'name',
        'description',
        'status',
        'priority',
        'owner',
        'completed',
        'progress_percent',
        'health',
        'start_date',
        'due_date',
        'latest_update',
        'created_at',
        'updated_at',
      ],
    })
    if (milestoneSection) {
      sections.push(milestoneSection)
    }
  }

  if (artifact?.artifact_type === 'decision') {
    const decisionSection = sectionFromRecord({
      id: 'decision-data',
      title: 'Decision Result',
      record: {
        matched_routes: Array.isArray(payload.matched_connector_ids) ? payload.matched_connector_ids : [],
        evaluations_count: Array.isArray(payload.evaluations) ? payload.evaluations.length : 0,
        no_match: payload.no_match,
        resolved_route_key: payload.resolved_route_key || outputState.resolved_route_key || '',
        resolved_route_path: payload.resolved_route_path || outputState.resolved_route_path || '',
      },
      keys: [
        'matched_routes',
        'evaluations_count',
        'no_match',
        'resolved_route_key',
        'resolved_route_path',
      ],
    })
    if (decisionSection) {
      sections.push(decisionSection)
    }
  }

  if (sections.length === 0) {
    const summarySection = sectionFromRecord({
      id: 'artifact-summary',
      title: 'Artifact Data Summary',
      record: {
        action: payload.action || outputState.action || '',
        node_type: payload.node_type || artifact?.node_type || '',
        output_action: outputState.action || '',
        input_field_count: Object.keys(inputContext).length,
        output_field_count: Object.keys(outputState).length,
        routing_field_count: Object.keys(routingState).length,
      },
      keys: [
        'action',
        'node_type',
        'output_action',
        'input_field_count',
        'output_field_count',
        'routing_field_count',
      ],
    })
    if (summarySection) {
      sections.push(summarySection)
    }
  }

  return sections
}

function entityContext(params) {
  const planId = parseId(params.planId)
  if (planId) {
    return { kind: 'plan', entityId: planId }
  }
  const milestoneId = parseId(params.milestoneId)
  if (milestoneId) {
    return { kind: 'milestone', entityId: milestoneId }
  }
  const memoryId = parseId(params.memoryId)
  if (memoryId) {
    return { kind: 'memory', entityId: memoryId }
  }
  const genericArtifactId = parseId(params.artifactId)
  if (genericArtifactId) {
    return { kind: 'artifact', entityId: null }
  }
  return { kind: null, entityId: null }
}

export default function ArtifactDetailPage() {
  const params = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const context = useMemo(() => entityContext(params), [params])
  const artifactId = useMemo(() => parseId(params.artifactId), [params.artifactId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const activePanelId = useMemo(
    () => normalizePanelId(searchParams.get('panel')),
    [searchParams],
  )

  useEffect(() => {
    const config = context.kind ? ENTITY_CONFIG[context.kind] : null
    if (!config || !artifactId) {
      setState({ loading: false, payload: null, error: 'Invalid artifact path.' })
      return
    }
    let cancelled = false
    const requestPromise = context.kind === 'artifact'
      ? getNodeArtifact(artifactId)
      : config.fetchArtifact(context.entityId, artifactId)
    requestPromise
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            loading: false,
            payload: null,
            error: errorMessage(error, `Failed to load ${config.label} artifact.`),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [artifactId, context.entityId, context.kind])

  const config = context.kind ? ENTITY_CONFIG[context.kind] : null
  const artifact = state.payload && typeof state.payload === 'object' && state.payload.item
    && typeof state.payload.item === 'object'
    ? state.payload.item
    : null
  const payloadJson = artifact && Object.prototype.hasOwnProperty.call(artifact, 'payload')
    ? (JSON.stringify(artifact.payload, null, 2) || 'null')
    : '{}'
  const headerEyebrow = config?.label === 'artifact' ? 'artifact detail' : `${config?.label || 'artifact'} artifact`
  const artifactType = String(artifact?.artifact_type || '').trim().toLowerCase()
  const artifactTypeLabel = String(artifact?.artifact_type || '').trim() || 'artifact'
  const backPath = context.kind === 'artifact'
    ? (artifactType ? `/artifacts/type/${artifactType}` : '/artifacts/type/task')
    : (config ? `${config.listPath}/${context.entityId}` : '/')
  const flowchartRunId = parseId(artifact?.flowchart_run_id)
  const flowchartRunHref = flowchartRunId ? `/flowcharts/runs/${flowchartRunId}` : ''
  const action = String(artifact?.payload?.action || '').trim()
  const dataSections = useMemo(() => buildDataSections(artifact), [artifact])
  const dataPresentation = useMemo(
    () => buildArtifactDataPresentation(artifact, dataSections),
    [artifact, dataSections],
  )

  function selectPanel(panelId) {
    const normalized = normalizePanelId(panelId)
    const updated = new URLSearchParams(searchParams)
    if (normalized === 'data') {
      updated.delete('panel')
    } else {
      updated.set('panel', normalized)
    }
    setSearchParams(updated, { replace: true })
  }

  return (
    <section className="artifact-detail-fixed-page" aria-label="Artifact detail">
      <article className="card panel-card artifact-detail-fixed-card">
        <PanelHeader
          title={artifact ? `Artifact ${artifact.id}` : 'Artifact detail'}
          titleClassName="artifact-detail-panel-title"
          className="node-panel-header artifact-detail-panel-header"
          actions={(
            <>
              {artifact ? <span className="status-chip status-open artifact-detail-type-chip">{artifactTypeLabel}</span> : null}
              <Link
                to={backPath}
                className="icon-button"
                aria-label="Back to artifact list"
                title="Back to artifact list"
              >
                <i className="fa-solid fa-arrow-left" />
              </Link>
              {flowchartRunHref ? (
                <Link
                  to={flowchartRunHref}
                  className="icon-button"
                  aria-label="Open run detail"
                  title="Open run detail"
                >
                  <i className="fa-solid fa-forward" />
                </Link>
              ) : null}
            </>
          )}
        />

        <div className="artifact-detail-fixed-body">
          {artifact ? (
            <div className="artifact-detail-inline-meta">
              <p className="eyebrow">{headerEyebrow}</p>
            </div>
          ) : null}
          {state.loading ? <p>Loading artifact...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}

          {artifact && config ? (
            <section className="settings-inner-layout artifact-detail-layout artifact-detail-fixed-layout">
              <aside className="settings-inner-sidebar" aria-label="Artifact detail panels">
                <p className="settings-inner-sidebar-title">Panels</p>
                <nav className="settings-inner-sidebar-nav">
                  {DETAIL_PANELS.map((item) => {
                    const isActive = item.id === activePanelId
                    return (
                      <button
                        key={item.id}
                        type="button"
                        className={`settings-inner-sidebar-link artifact-panel-nav-button${isActive ? ' is-active' : ''}`}
                        aria-pressed={isActive}
                        onClick={() => selectPanel(item.id)}
                      >
                        <span className="settings-inner-sidebar-link-main">
                          <i className={item.icon} aria-hidden="true" />
                          <span>{item.label}</span>
                        </span>
                        <i className="fa-solid fa-chevron-right" aria-hidden="true" />
                      </button>
                    )
                  })}
                </nav>
              </aside>

              <section className="stack settings-inner-content artifact-detail-content">
                {activePanelId === 'metadata' ? (
                  <article className="subcard artifact-detail-panel">
                    <p className="eyebrow">metadata</p>
                    <div className="artifact-detail-panel-body">
                      <dl className="meta-list meta-list-compact artifact-detail-meta-list">
                        <div>
                          <dt>Action</dt>
                          <dd>{action || '-'}</dd>
                        </div>
                        <div>
                          <dt>Variant</dt>
                          <dd>{artifact.variant_key || '-'}</dd>
                        </div>
                        <div>
                          <dt>Type</dt>
                          <dd>{artifact.artifact_type || '-'}</dd>
                        </div>
                        <div>
                          <dt>Flowchart</dt>
                          <dd>f{artifact.flowchart_id || '-'} / n{artifact.flowchart_node_id || '-'} / r{artifact.flowchart_run_id || '-'}</dd>
                        </div>
                        <div>
                          <dt>Run node</dt>
                          <dd>{artifact.flowchart_run_node_id || '-'}</dd>
                        </div>
                        <div>
                          <dt>Created</dt>
                          <dd>{artifact.created_at || '-'}</dd>
                        </div>
                        <div>
                          <dt>Updated</dt>
                          <dd>{artifact.updated_at || '-'}</dd>
                        </div>
                        <div>
                          <dt>Request id</dt>
                          <dd>{artifact.request_id || '-'}</dd>
                        </div>
                        <div>
                          <dt>Correlation id</dt>
                          <dd>{artifact.correlation_id || '-'}</dd>
                        </div>
                      </dl>
                    </div>
                  </article>
                ) : null}

                {activePanelId === 'payload' ? (
                  <article className="subcard artifact-detail-panel">
                    <p className="eyebrow">payload</p>
                    <div className="artifact-detail-panel-body">
                      <pre className="artifact-detail-payload">{payloadJson}</pre>
                    </div>
                  </article>
                ) : null}

                {activePanelId === 'data' ? (
                  <article className="subcard artifact-detail-panel">
                    <p className="eyebrow">data</p>
                    <div className="artifact-detail-panel-body">
                      {dataPresentation ? (
                      <section className="artifact-memory-layout">
                        <section className="artifact-data-section artifact-memory-primary">
                            <h3 className="artifact-data-section-title">{dataPresentation.title}</h3>
                          <details className="artifact-memory-meta-accordion">
                            <summary>Metadata</summary>
                              {dataPresentation.metadataEntries.length > 0 ? (
                                <dl className="kv-grid artifact-data-grid">
                                  {dataPresentation.metadataEntries.map((entry) => (
                                    <div key={`artifact-meta-${entry.key}`}>
                                      <dt>{entry.label}</dt>
                                      <dd>{entry.value}</dd>
                                    </div>
                                  ))}
                                </dl>
                              ) : (
                                <p className="muted artifact-memory-meta-empty">No metadata fields available.</p>
                              )}
                          </details>
                          <section className="artifact-memory-description">
                              <p className="eyebrow">{dataPresentation.contentTitle}</p>
                            <pre className="artifact-memory-description-code">
                                {dataPresentation.contentText || '-'}
                            </pre>
                          </section>
                        </section>
                          {dataPresentation.secondarySections.length > 0 ? (
                          <div className="stack-sm artifact-data-sections artifact-data-sections-secondary">
                              {dataPresentation.secondarySections.map((section) => (
                              <section key={section.id} className="artifact-data-section">
                                <h3 className="artifact-data-section-title">{section.title}</h3>
                                <dl className="kv-grid artifact-data-grid">
                                  {section.entries.map((entry) => (
                                    <div key={`${section.id}-${entry.key}`}>
                                      <dt>{entry.label}</dt>
                                      <dd>{entry.value}</dd>
                                    </div>
                                  ))}
                                </dl>
                              </section>
                            ))}
                          </div>
                        ) : null}
                      </section>
                    ) : (
                      <p className="muted artifact-data-empty">
                        No structured data fields were found in this artifact payload.
                      </p>
                    )}
                  </div>
                </article>
              ) : null}
              </section>
            </section>
          ) : null}
        </div>
      </article>
    </section>
  )
}
