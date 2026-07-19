import type { Session } from '../types'

function points(value: number[][] | undefined): string {
  return (value ?? []).map((point) => `${point[0]},${point[1]}`).join(' ')
}

export function TracePlot({ trace }: { trace: Session['trace'] }) {
  const frame = trace?.frame ?? [2304, 1296]
  const hasTrace = Boolean(trace?.reference?.length || trace?.red?.length)
  if (!hasTrace) return <p className="muted">Trace data was not captured for this session.</p>
  return (
    <div className="trace-plot">
      <svg viewBox={`0 0 ${frame[0]} ${frame[1]}`} role="img" aria-label="Reference and captured trace overlay">
        <polyline points={points(trace?.reference)} fill="none" stroke="#2e64a1" strokeWidth="22" strokeLinecap="round" strokeLinejoin="round" />
        <polyline points={points(trace?.red)} fill="none" stroke="#d34b45" strokeWidth="18" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="trace-legend"><span className="reference-line" />Reference <span className="attempt-line" />Attempt</div>
    </div>
  )
}

