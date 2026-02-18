import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getMemoryArtifact, getMilestoneArtifact, getPlanArtifact } from '../lib/studioApi'

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

const ENTITY_CONFIG = {
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
  return { kind: null, entityId: null }
}

export default function ArtifactDetailPage() {
  const params = useParams()
  const context = useMemo(() => entityContext(params), [params])
  const artifactId = useMemo(() => parseId(params.artifactId), [params.artifactId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    const config = context.kind ? ENTITY_CONFIG[context.kind] : null
    if (!config || !context.entityId || !artifactId) {
      setState({ loading: false, payload: null, error: 'Invalid artifact path.' })
      return
    }
    let cancelled = false
    config.fetchArtifact(context.entityId, artifactId)
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
  const payloadJson = artifact?.payload && typeof artifact.payload === 'object'
    ? JSON.stringify(artifact.payload, null, 2)
    : '{}'
  const backPath = config ? `${config.listPath}/${context.entityId}` : '/'
  const flowchartRunId = parseId(artifact?.flowchart_run_id)
  const flowchartRunHref = flowchartRunId ? `/flowcharts/runs/${flowchartRunId}` : ''
  const action = String(artifact?.payload?.action || '').trim()

  return (
    <section className="stack" aria-label="Artifact detail">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            <Link to={backPath} className="btn btn-secondary">
              <i className="fa-solid fa-arrow-left" />
              back
            </Link>
            {flowchartRunHref ? (
              <Link to={flowchartRunHref} className="btn btn-secondary">
                <i className="fa-solid fa-forward" />
                run detail
              </Link>
            ) : null}
          </div>
        </div>

        {state.loading ? <p>Loading artifact...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}

        {artifact && config ? (
          <>
            <div className="card-header">
              <div>
                <p className="eyebrow">{config.label} artifact</p>
                <h2 className="section-title">Artifact {artifact.id}</h2>
              </div>
            </div>

            <dl className="meta-list meta-list-compact" style={{ marginTop: '20px' }}>
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

            <div className="subcard" style={{ marginTop: '20px' }}>
              <p className="eyebrow">payload</p>
              <pre style={{ marginTop: '12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{payloadJson}</pre>
            </div>
          </>
        ) : null}
      </article>
    </section>
  )
}
