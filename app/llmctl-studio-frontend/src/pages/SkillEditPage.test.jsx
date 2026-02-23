import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import SkillEditPage from './SkillEditPage'

function SkillRouteProbe() {
  const location = useLocation()
  return (
    <>
      <p>Skill detail route</p>
      <p data-testid="skill-route-path">{location.pathname}</p>
      <p data-testid="skill-route-search">{location.search}</p>
    </>
  )
}

describe('SkillEditPage', () => {
  test('redirects edit route to skill metadata section', async () => {
    render(
      <MemoryRouter initialEntries={['/skills/7/edit?version=1.0.0']}>
        <Routes>
          <Route path="/skills/:skillId/edit" element={<SkillEditPage />} />
          <Route path="/skills/:skillId" element={<SkillRouteProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Skill detail route')).toBeInTheDocument()
    expect(screen.getByTestId('skill-route-path')).toHaveTextContent('/skills/7')
    const search = screen.getByTestId('skill-route-search').textContent || ''
    expect(search).toContain('version=1.0.0')
    expect(search).toContain('section=metadata')
  })
})
