import { Navigate, useParams, useSearchParams } from 'react-router-dom'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export default function SkillEditPage() {
  const { skillId } = useParams()
  const [searchParams] = useSearchParams()
  const parsedSkillId = parseId(skillId)

  if (!parsedSkillId) {
    return <p className="error-text">Invalid skill id.</p>
  }

  const nextSearchParams = new URLSearchParams(searchParams)
  nextSearchParams.set('section', 'metadata')
  const nextSearch = nextSearchParams.toString()
  const to = `/skills/${parsedSkillId}${nextSearch ? `?${nextSearch}` : ''}`
  return <Navigate to={to} replace />
}
