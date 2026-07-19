export type User = {
  id: number
  username: string
  display_name: string | null
  notes: string | null
  session_count: number
  latest_session_at: string | null
}

export type ModelResult = {
  status: 'pending' | 'completed' | 'unavailable' | 'error'
  adapter: string
  model_version: string | null
  regression_score: number | null
  regression_flag: boolean | null
  confidence: number | null
  overall_pattern: string | null
  result: {
    observations?: { statement: string; metric_keys: string[] }[]
    conflicts_or_limitations?: string[]
  } | null
  error_code: string | null
  error_detail: string | null
}

export type Change = {
  reference: number
  current: number
  absolute_change: number
  percent_change: number | null
  direction: 'improved' | 'declined' | 'stable'
}

export type DeterministicComparison = {
  compatible: boolean
  policy_version: string
  overall?: string
  changes: Record<string, Change>
}

export type Session = {
  id: number
  session_id: string
  device_id: string
  schema_version: string
  created_at: string
  received_at: string
  user: { id: number; username: string; display_name: string | null }
  task: { type: string; version: string; difficulty?: string | number; hand?: string }
  timing: { started_at?: string; duration_ms?: number }
  scores: {
    accuracy: number | null
    stability: number | null
    accuracy_band?: string
    stability_band?: string
    version?: string
  }
  metrics: Record<string, number | null>
  quality: Record<string, unknown> & { calibration_valid?: boolean; warnings?: string[] }
  trace?: { frame?: [number, number]; reference?: number[][]; red?: number[][] }
  model_result: ModelResult | null
  deterministic_comparison: DeterministicComparison | null
}

export type TrendPoint = {
  session_id: string
  device_id: string
  created_at: string
  task: Session['task']
  accuracy: number | null
  stability: number | null
  completion_time_seconds: number | null
  coverage_pct: number | null
}

export type PairComparison = {
  reference: Session
  current: Session
  deterministic_comparison: DeterministicComparison
  model_prediction: ModelResult | null
}

