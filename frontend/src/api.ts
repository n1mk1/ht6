import type { PairComparison, Session, TrendPoint, User } from './types'

const API_ROOT = import.meta.env.VITE_API_URL ?? '/api/v1'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, init)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json()
      message = body.detail?.message ?? body.detail?.code ?? message
    } catch {
      // Keep the status-based message for non-JSON failures.
    }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  users: () => request<User[]>('/users'),
  resolveUser: (username: string) => request<{ created: boolean; user: User }>('/users/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }),
  }),
  sessions: (userId: number) => request<Session[]>(`/users/${userId}/sessions`),
  latest: (userId: number) => request<Session>(`/users/${userId}/sessions/latest`),
  trends: (userId: number) => request<{ user_id: number; series: TrendPoint[] }>(`/users/${userId}/trends`),
  session: (deviceId: string, sessionId: string) =>
    request<Session>(`/sessions/${encodeURIComponent(deviceId)}/${encodeURIComponent(sessionId)}`),
  comparison: (reference: Session, current: Session) => {
    const params = new URLSearchParams({
      reference_device_id: reference.device_id,
      reference_session_id: reference.session_id,
      current_device_id: current.device_id,
      current_session_id: current.session_id,
    })
    return request<PairComparison>(`/comparisons?${params}`)
  },
}
