import { ArrowRight, GitCompareArrows } from 'lucide-react'
import { metric, metricLabels, titleCase } from '../format'
import type { PairComparison, Session } from '../types'
import { EmptyState, ErrorState, LoadingState } from './States'

type Props = {
  sessions: Session[]
  comparison: PairComparison | null
  loading: boolean
  error: string | null
  referenceId: string
  currentId: string
  onReference: (id: string) => void
  onCurrent: (id: string) => void
  onCompare: () => void
}

const key = (session: Session) => `${session.device_id}::${session.session_id}`

export function ComparisonView(props: Props) {
  if (props.sessions.length < 2) {
    return <EmptyState title="Two sessions required" message="Record another compatible run to open side-by-side comparison." />
  }
  return (
    <div className="compare-view">
      <section className="compare-controls" aria-label="Run comparison controls">
        <div>
          <label htmlFor="reference-run">Reference run</label>
          <select id="reference-run" value={props.referenceId} onChange={(event) => props.onReference(event.target.value)}>
            {props.sessions.map((session) => <option key={key(session)} value={key(session)}>{new Date(session.created_at).toLocaleDateString()} / {session.session_id}</option>)}
          </select>
        </div>
        <ArrowRight size={20} />
        <div>
          <label htmlFor="current-run">Current run</label>
          <select id="current-run" value={props.currentId} onChange={(event) => props.onCurrent(event.target.value)}>
            {props.sessions.map((session) => <option key={key(session)} value={key(session)}>{new Date(session.created_at).toLocaleDateString()} / {session.session_id}</option>)}
          </select>
        </div>
        <button className="primary-button" onClick={props.onCompare}><GitCompareArrows size={17} /> Compare</button>
      </section>
      {props.loading && <LoadingState label="Comparing compatible runs" />}
      {props.error && <ErrorState message={props.error} />}
      {!props.loading && !props.error && !props.comparison && <EmptyState title="Choose two runs" message="Select a reference and current run, then compare them." />}
      {props.comparison && (
        <section className="comparison-table-wrap">
          <div className="comparison-title">
            <span className="section-kicker">Deterministic comparison</span>
            <h2>{titleCase(props.comparison.deterministic_comparison.overall)}</h2>
            <p>Only compatible task metadata is accepted. Deltas are direct measurements, not model predictions.</p>
          </div>
          <div className="comparison-table" role="table" aria-label="Side-by-side run comparison">
            <div className="comparison-row table-header" role="row"><span>Measurement</span><span>Reference</span><span>Current</span><span>Change</span></div>
            {Object.entries(props.comparison.deterministic_comparison.changes).map(([name, change]) => {
              const info = metricLabels[name] ?? { label: titleCase(name), suffix: '' }
              return <div className="comparison-row" role="row" key={name}>
                <strong>{info.label}</strong>
                <span>{metric(change.reference, info.suffix, 2)}</span>
                <span>{metric(change.current, info.suffix, 2)}</span>
                <span className={`direction-${change.direction}`}>{change.absolute_change > 0 ? '+' : ''}{change.absolute_change} / {titleCase(change.direction)}</span>
              </div>
            })}
          </div>
        </section>
      )}
    </div>
  )
}

