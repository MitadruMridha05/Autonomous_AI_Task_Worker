export type RunStatus = 'queued' | 'planning' | 'running' | 'waiting' | 'completed' | 'no_action_needed' | 'failed' | 'cancelled' | 'needs_clarification' | 'declined'
export type TraceEvent = { t?: number; kind: string; step?: number; name?: string; text?: string; preview?: string; ok?: boolean; message?: string; summary?: string; arguments?: Record<string, unknown>; approved?: boolean; how?: string }
export type RunResult = { run_id: string; task: string; status: string; summary: string; evidence: string[]; steps: number; usage: Record<string, number>; duration_s: number; model: string; prompt_version: string; trace: TraceEvent[]; trace_path?: string | null }
export type Run = { run_id: string; task: string; status: RunStatus | string; phase: string; trace: TraceEvent[]; current_action: string; created_at: number; updated_at: number; finished_at?: number; result?: RunResult | null; error?: string | null; settings?: Record<string, unknown> }
export type Health = { status: string }
