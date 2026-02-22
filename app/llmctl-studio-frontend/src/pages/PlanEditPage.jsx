import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getPlanEdit, updatePlan } from '../lib/studioApi'
import PanelHeader from '../components/PanelHeader'

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

function toInputDateTime(value) {
  const normalized = String(value || '').trim()
  if (!normalized || normalized === '-') {
    return ''
  }
  const withT = normalized.includes(' ') ? normalized.replace(' ', 'T') : normalized
  return withT.length >= 16 ? withT.slice(0, 16) : withT
}

export default function PlanEditPage() {
  const navigate = useNavigate()
  const { planId } = useParams()
  const parsedPlanId = useMemo(() => parseId(planId), [planId])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    completedAt: '',
  })

  useEffect(() => {
    if (!parsedPlanId) {
      setState({ loading: false, payload: null, error: 'Invalid plan id.' })
      return
    }
    let cancelled = false
    getPlanEdit(parsedPlanId)
      .then((payload) => {
        if (!cancelled) {
          const plan = payload && payload.plan && typeof payload.plan === 'object' ? payload.plan : null
          setState({ loading: false, payload, error: '' })
          if (plan) {
            setForm({
              name: String(plan.name || ''),
              description: String(plan.description || ''),
              completedAt: toInputDateTime(plan.completed_at),
            })
          }
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load plan edit data.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedPlanId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const plan = payload && payload.plan && typeof payload.plan === 'object' ? payload.plan : null

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedPlanId) {
      return
    }
    setActionError('')
    setSaving(true)
    try {
      await updatePlan(parsedPlanId, form)
      navigate(`/plans/${parsedPlanId}`)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update plan.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit plan">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            {plan ? (
              <Link to={`/plans/${plan.id}`} className="btn btn-secondary">
                <i className="fa-solid fa-arrow-left" />
                back to plan
              </Link>
            ) : null}
            <Link to="/plans" className="btn btn-secondary">
              <i className="fa-solid fa-list" />
              all plans
            </Link>
          </div>
        </div>

        <PanelHeader title="Edit Plan" />

        {state.loading ? <p style={{ marginTop: '20px' }}>Loading plan...</p> : null}
        {state.error ? <p className="error-text" style={{ marginTop: '12px' }}>{state.error}</p> : null}

        {!state.loading && !state.error ? (
          <form className="form-grid" style={{ marginTop: '20px' }} onSubmit={handleSubmit}>
            <label className="field">
              <span>name</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>completed at (optional)</span>
              <input
                type="datetime-local"
                value={form.completedAt}
                onChange={(event) => setForm((current) => ({ ...current, completedAt: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>description (optional)</span>
              <textarea
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={saving}>
                <i className="fa-solid fa-floppy-disk" />
                {saving ? 'saving changes...' : 'save changes'}
              </button>
              {plan ? (
                <Link className="btn btn-secondary" to={`/plans/${plan.id}`}>
                  <i className="fa-solid fa-arrow-left" />
                  cancel
                </Link>
              ) : null}
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}
