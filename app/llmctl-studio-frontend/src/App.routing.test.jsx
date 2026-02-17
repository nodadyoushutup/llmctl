import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import App from './App'

function renderAt(pathname) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <App />
    </MemoryRouter>,
  )
}

describe('App routing', () => {
  test('root route redirects to legacy overview bridge', async () => {
    renderAt('/')
    const iframe = await screen.findByTitle('Legacy Studio page')
    expect(iframe).toHaveAttribute('src', '/api/overview')
  })

  test('migration route keeps native react migration hub available', async () => {
    renderAt('/migration')
    expect(await screen.findByText('Frontend Migration Hub')).toBeInTheDocument()
    expect(screen.getByText('Stage 5 scope')).toBeInTheDocument()
  })

  test('agents route is native react', async () => {
    renderAt('/agents')
    expect(await screen.findByText('Native React replacement for the legacy agents list and row actions.')).toBeInTheDocument()
  })

  test('unknown route still bridges through backend api path', async () => {
    renderAt('/does-not-exist')
    const iframe = await screen.findByTitle('Legacy Studio page')
    expect(iframe).toHaveAttribute('src', '/api/does-not-exist')
  })
})
