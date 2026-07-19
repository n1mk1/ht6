import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { Session } from './types'

const user = {
  id: 1,
  username: 'participant-001',
  display_name: 'Alex Morgan',
  notes: null,
  session_count: 2,
  latest_session_at: '2026-07-19T09:00:00Z',
}

function session(id: string, date: string, accuracy: number): Session {
  return {
    id: id === 'session-002' ? 2 : 1,
    session_id: id,
    device_id: 'qnx_pi_23',
    schema_version: '3.0',
    created_at: date,
    received_at: date,
    user: { id: 1, username: user.username, display_name: user.display_name },
    task: { type: 'path_tracing', version: 'mat_v1', difficulty: 1 },
    timing: { duration_ms: 42300 },
    scores: { accuracy, stability: 82, accuracy_band: 'very high', stability_band: 'very high' },
    metrics: {
      accuracy_score: accuracy,
      stability_score: 82,
      completion_time_seconds: 42.3,
      coverage_pct: 91.2,
      mean_dev_mm: 2.2,
      max_dev_mm: 6.4,
      rms_dev_mm: 2.8,
      tremor_rms_deg_s: 6.1,
      gyro_rms_deg_s: 10.2,
      peak_angular_velocity_deg_s: 31.5,
    },
    quality: { calibration_valid: true, warnings: [], imu_samples_received: 6380 },
    trace: { frame: [100, 50], reference: [[0, 25], [100, 25]], red: [[0, 28], [100, 26]] },
    model_result: {
      status: 'unavailable',
      adapter: 'freesolo_http_v2',
      model_version: null,
      regression_score: null,
      regression_flag: null,
      confidence: null,
      overall_pattern: null,
      result: null,
      error_code: 'missing_required_metrics',
      error_detail: null,
    },
    deterministic_comparison: id === 'session-002' ? {
      compatible: true,
      policy_version: 'praxis-comparison-1.0.0',
      overall: 'improved',
      changes: {
        accuracy_score: { reference: 80, current: accuracy, absolute_change: accuracy - 80, percent_change: 6.25, direction: 'improved' },
        completion_time_seconds: { reference: 45, current: 42.3, absolute_change: -2.7, percent_change: -6, direction: 'improved' },
      },
    } : null,
  }
}

const latest = session('session-002', '2026-07-19T09:00:00Z', 85)
const prior = session('session-001', '2026-07-18T09:00:00Z', 80)

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

function mockApi() {
  vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
    const url = String(input)
    if (url.endsWith('/users/resolve')) return response({ created: false, user })
    if (url.endsWith('/users')) return response([user])
    if (url.endsWith('/users/1/sessions')) return response([latest, prior])
    if (url.endsWith('/users/1/sessions/latest')) return response(latest)
    if (url.endsWith('/users/1/trends')) return response({ user_id: 1, series: [prior, latest].map((item) => ({
      session_id: item.session_id,
      device_id: item.device_id,
      created_at: item.created_at,
      task: item.task,
      accuracy: item.scores.accuracy,
      stability: item.scores.stability,
      completion_time_seconds: item.metrics.completion_time_seconds,
      coverage_pct: item.metrics.coverage_pct,
    })) })
    if (url.includes('/sessions/qnx_pi_23/session-001')) return response(prior)
    if (url.includes('/comparisons?')) return response({
      reference: prior,
      current: latest,
      deterministic_comparison: latest.deterministic_comparison,
      model_prediction: latest.model_result,
    })
    return response({ detail: { code: 'not_found' } }, 404)
  }))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

async function enterDashboard() {
  const actor = userEvent.setup()
  expect(screen.getByRole('heading', { name: 'Enter your username' })).toBeInTheDocument()
  expect(screen.queryByText(/FreeSOLO/i)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /view my sessions/i })).toBeInTheDocument()
  await actor.type(screen.getByLabelText('Username'), 'participant-001')
  await actor.click(screen.getByRole('button', { name: /view my sessions/i }))
  return actor
}

describe('Praxis dashboard', () => {
  it('loads the participant overview, raw metrics, quality, trend, and model state', async () => {
    mockApi()
    render(<App />)
    await enterDashboard()
    expect(await screen.findByRole('heading', { name: 'Alex Morgan' })).toBeInTheDocument()
    expect(await screen.findByText('Latest session')).toBeInTheDocument()
    expect(screen.getByText('85.0')).toBeInTheDocument()
    expect(screen.getByText('Quality checks passed')).toBeInTheDocument()
    expect(screen.getByText('Analysis unavailable')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart')).toBeInTheDocument()
    expect(screen.getByText(/not a diagnosis or validated clinical deterioration/i)).toBeInTheDocument()
  })

  it('opens a historical run detail and performs a side-by-side comparison', async () => {
    mockApi()
    render(<App />)
    const actor = await enterDashboard()
    await screen.findByRole('heading', { name: 'Alex Morgan' })
    await actor.click(screen.getByRole('button', { name: /session history/i }))
    await actor.click(screen.getByRole('button', { name: /jul 18, 2026/i }))
    expect(await screen.findByText('Run details')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /reference and captured trace overlay/i })).toBeInTheDocument()

    await actor.click(screen.getByRole('button', { name: /compare runs/i }))
    await actor.click(screen.getByRole('button', { name: /^compare$/i }))
    expect(await screen.findByRole('table', { name: /side-by-side run comparison/i })).toBeInTheDocument()
    expect(screen.getByText(/direct measurements/i)).toBeInTheDocument()
  })

  it('creates a username before QNX ingestion and shows the waiting state', async () => {
    const emptyUser = { ...user, id: 2, username: 'new-person', display_name: null, session_count: 0, latest_session_at: null }
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/users/resolve')) return response({ created: true, user: emptyUser }, 201)
      if (url.endsWith('/users/2/sessions')) return response([])
      if (url.endsWith('/users/2/trends')) return response({ user_id: 2, series: [] })
      return response({ detail: { code: 'not_found' } }, 404)
    }))
    render(<App />)
    const actor = userEvent.setup()
    await actor.type(screen.getByLabelText('Username'), 'new-person')
    await actor.click(screen.getByRole('button', { name: /view my sessions/i }))
    expect(await screen.findByText('No sessions yet')).toBeInTheDocument()
    expect(screen.getByText(/use this same username on QNX/i)).toBeInTheDocument()
  })

  it('keeps username resolution errors on the entry page', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ detail: { message: 'Service offline' } }, 503)))
    render(<App />)
    const actor = userEvent.setup()
    await actor.type(screen.getByLabelText('Username'), 'participant-001')
    await actor.click(screen.getByRole('button', { name: /view my sessions/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Service offline')
    expect(screen.getByRole('heading', { name: 'Enter your username' })).toBeInTheDocument()
  })

  it('returns to username entry from switch user', async () => {
    mockApi()
    render(<App />)
    const actor = await enterDashboard()
    await screen.findByRole('heading', { name: 'Alex Morgan' })
    await actor.click(screen.getByRole('button', { name: /switch user/i }))
    expect(screen.getByRole('heading', { name: 'Enter your username' })).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toHaveValue('participant-001')
  })
})
