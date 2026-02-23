import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import SkillDetailPage from './SkillDetailPage'
import { getSkill, getSkillEdit, updateSkill } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getSkill: vi.fn(),
  getSkillEdit: vi.fn(),
  updateSkill: vi.fn(),
}))

const SKILL_PAYLOAD = {
  skill: {
    id: 7,
    name: 'chromium-screenshot',
    display_name: 'Chromium Screenshot',
    description: 'Capture and audit frontend screenshots.',
    status: 'active',
    latest_version: '1.1.0',
    binding_count: 1,
  },
  versions: [
    { id: 11, version: '1.1.0' },
    { id: 10, version: '1.0.0' },
  ],
  selected_version: '1.1.0',
  preview: {
    version_id: 11,
    version: '1.1.0',
    files: [
      { id: 1, path: 'SKILL.md', size_bytes: 120 },
      { id: 2, path: 'scripts/capture.sh', size_bytes: 62 },
    ],
  },
  attached_agents: [
    { id: 4, name: 'Builder', status: 'idle', description: 'Build agent', updated_at: '2026-02-22 17:00' },
  ],
  skill_is_git_read_only: false,
}

const SKILL_EDIT_PAYLOAD = {
  skill: {
    id: 7,
    display_name: 'Chromium Screenshot',
    description: 'Capture and audit frontend screenshots.',
    status: 'active',
    source_ref: 'app/llmctl-studio-backend/seed-skills/chromium-screenshot',
  },
  latest_version: {
    id: 11,
    version: '1.1.0',
  },
  latest_skill_md: '# Chromium Screenshot',
  latest_non_skill_files: [
    { path: 'scripts/capture.sh', size_bytes: 62, is_binary: false },
  ],
  skill_status_options: [
    { value: 'active', label: 'Active' },
    { value: 'disabled', label: 'Disabled' },
  ],
  max_upload_bytes: 10 * 1024 * 1024,
}

function renderPage(initialEntry = '/skills/7') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/skills/:skillId" element={<SkillDetailPage />} />
          <Route path="/agents/:agentId" element={<p>Agent detail route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

describe('SkillDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getSkill.mockResolvedValue(SKILL_PAYLOAD)
    getSkillEdit.mockResolvedValue(SKILL_EDIT_PAYLOAD)
    updateSkill.mockResolvedValue({ ok: true, skill: { id: 7 } })
  })

  test('renders section nav and metadata form editor', async () => {
    renderPage('/skills/7')

    expect(await screen.findByRole('heading', { name: 'Skill Metadata' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Metadata' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Files' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Attached Agents' })).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByLabelText('Display name')).toHaveValue('Chromium Screenshot')
    })
    expect(screen.getByLabelText('Description')).toHaveValue('Capture and audit frontend screenshots.')
    expect(screen.queryByText('Existing files draft JSON')).not.toBeInTheDocument()
    expect(screen.queryByText('Extra files draft JSON')).not.toBeInTheDocument()
  })

  test('files section saves structured existing/new file drafts', async () => {
    renderPage('/skills/7?section=files')
    expect(await screen.findByRole('heading', { name: 'Skill Files' })).toBeInTheDocument()
    await screen.findByDisplayValue('scripts/capture.sh')

    fireEvent.click(screen.getByRole('button', { name: 'Add file row' }))
    const pathInput = await screen.findByLabelText('New file path')
    fireEvent.change(pathInput, { target: { value: 'references/usage.md' } })
    fireEvent.change(screen.getByLabelText('New file content'), { target: { value: '# Usage' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => {
      expect(updateSkill).toHaveBeenCalledTimes(1)
    })
    expect(updateSkill).toHaveBeenCalledWith(7, expect.objectContaining({
      displayName: 'Chromium Screenshot',
      description: 'Capture and audit frontend screenshots.',
      status: 'active',
      sourceRef: 'app/llmctl-studio-backend/seed-skills/chromium-screenshot',
      existingFiles: [
        {
          original_path: 'scripts/capture.sh',
          path: 'scripts/capture.sh',
          delete: false,
        },
      ],
      extraFiles: [
        {
          path: 'references/usage.md',
          content: '# Usage',
        },
      ],
    }))
  })

  test('attached agents section keeps row-link navigation', async () => {
    const { container } = renderPage('/skills/7?section=agents')
    expect(await screen.findByRole('heading', { name: 'Attached Agents' })).toBeInTheDocument()

    const row = container.querySelector('tr.table-row-link')
    const statusCell = row?.querySelector('td:nth-child(2)')
    expect(statusCell).toBeTruthy()
    fireEvent.click(statusCell)

    expect(await screen.findByText('Agent detail route')).toBeInTheDocument()
  })
})
