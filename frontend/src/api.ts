import type { Health, Run, RunResult } from './types'

const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, { headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) }, ...init })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try { const body = await response.json(); message = body?.error?.message || body?.detail || message } catch { /* keep status */ }
    throw new Error(message)
  }
  return response.json()
}
export const api = {
  health: () => request<Health>('/api/health'),
  runs: () => request<Run[]>('/api/worker/runs'),
  run: (payload: { task: string; max_steps: number; approve_risky: boolean; provider?: string; model?: string }) => request<Run>('/api/worker/run', { method: 'POST', body: JSON.stringify(payload) }),
  getRun: (id: string) => request<Run>(`/api/worker/runs/${id}`),
  cancel: (id: string) => request<Run>(`/api/worker/runs/${id}/cancel`, { method: 'POST' }),
  settings: () => request<Record<string, string | number>>('/api/worker/settings'),
  audit: () => request<Array<Record<string, string | number>>>('/api/audit?limit=8'),
}
export type { RunResult }
