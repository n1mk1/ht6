import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Gauge, Move3d, Ruler, Timer, Waves } from 'lucide-react'
import { formatDate, metric, titleCase } from '../format'
import type { Session } from '../types'
import { ModelPanel } from './ModelPanel'
import { TracePlot } from './TracePlot'

type MetricCardProps = {
  label: string
  value: string
  detail: string
  icon: ReactNode
  tone?: string
}

function MetricCard({ label, value, detail, icon, tone = '' }: MetricCardProps) {
  return (
    <div className={`metric-card ${tone}`}>
      <div className="metric-icon">{icon}</div>
      <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
    </div>
  )
}

function ComparisonSummary({ session }: { session: Session }) {
  const comparison = session.deterministic_comparison
  if (!comparison) {
    return (
      <section className="comparison-summary comparison-none">
        <span className="section-kicker">Deterministic comparison</span>
        <h3>No compatible earlier run</h3>
        <p>A comparison will appear after another run with the same task type, version, difficulty, and hand metadata.</p>
      </section>
    )
  }
  const items = Object.entries(comparison.changes).slice(0, 4)
  return (
    <section className="comparison-summary">
      <div>
        <span className="section-kicker">Deterministic comparison</span>
        <h3>{titleCase(comparison.overall)} versus previous compatible run</h3>
        <p>Direct arithmetic under {comparison.policy_version}. This is separate from the model prediction.</p>
      </div>
      <div className="delta-list">
        {items.map(([name, change]) => (
          <div key={name}>
            <span>{titleCase(name)}</span>
            <strong className={`direction-${change.direction}`}>{change.absolute_change > 0 ? '+' : ''}{change.absolute_change}</strong>
          </div>
        ))}
      </div>
    </section>
  )
}

export function SessionView({ session, latest = false }: { session: Session; latest?: boolean }) {
  const warnings = session.quality.warnings ?? []
  return (
    <div className="session-view">
      <div className="session-heading">
        <div>
          <span className="section-kicker">{latest ? 'Latest session' : 'Run details'}</span>
          <h2>{formatDate(session.created_at, true)}</h2>
          <p>{titleCase(session.task.type)} / {session.task.version} / Difficulty {session.task.difficulty ?? 'Not set'}</p>
        </div>
        <div className="session-meta">
          <span>{session.session_id}</span>
          <span>{session.device_id}</span>
        </div>
      </div>

      <div className="metric-grid">
        <MetricCard label="Accuracy" value={metric(session.scores.accuracy)} detail={titleCase(session.scores.accuracy_band)} icon={<Gauge size={19} />} tone="metric-green" />
        <MetricCard label="Stability" value={metric(session.scores.stability)} detail={titleCase(session.scores.stability_band)} icon={<Waves size={19} />} tone="metric-blue" />
        <MetricCard label="Completion" value={metric(session.metrics.completion_time_seconds, ' s')} detail="Raw timing" icon={<Timer size={19} />} />
        <MetricCard label="Coverage" value={metric(session.metrics.coverage_pct, '%')} detail="Detected trace coverage" icon={<Ruler size={19} />} />
      </div>

      <ComparisonSummary session={session} />
      <ModelPanel result={session.model_result} />

      <div className="detail-grid">
        <section className="panel trace-panel">
          <div className="panel-heading"><div><span className="section-kicker"><Move3d size={14} /> Raw trace</span><h3>Captured path</h3></div></div>
          <TracePlot trace={session.trace} />
        </section>
        <section className="panel movement-panel">
          <div className="panel-heading"><div><span className="section-kicker"><Waves size={14} /> Raw measurements</span><h3>Movement metrics</h3></div></div>
          <dl className="measurement-list">
            <div><dt>Mean deviation</dt><dd>{metric(session.metrics.mean_dev_mm, ' mm', 2)}</dd></div>
            <div><dt>Maximum deviation</dt><dd>{metric(session.metrics.max_dev_mm, ' mm', 2)}</dd></div>
            <div><dt>RMS deviation</dt><dd>{metric(session.metrics.rms_dev_mm, ' mm', 2)}</dd></div>
            <div><dt>Tremor RMS</dt><dd>{metric(session.metrics.tremor_rms_deg_s, ' deg/s', 2)}</dd></div>
            <div><dt>Gyro RMS</dt><dd>{metric(session.metrics.gyro_rms_deg_s, ' deg/s', 2)}</dd></div>
            <div><dt>Peak angular velocity</dt><dd>{metric(session.metrics.peak_angular_velocity_deg_s, ' deg/s', 2)}</dd></div>
          </dl>
        </section>
      </div>

      <section className={`quality-strip ${warnings.length ? 'quality-warning' : 'quality-good'}`}>
        {warnings.length ? <AlertTriangle size={19} /> : <CheckCircle2 size={19} />}
        <div>
          <strong>{warnings.length ? `${warnings.length} quality warning${warnings.length === 1 ? '' : 's'}` : 'Quality checks passed'}</strong>
          <p>{warnings.length ? warnings.map(titleCase).join(', ') : `Calibration valid / ${Number(session.quality.imu_samples_received ?? 0).toLocaleString()} IMU samples received`}</p>
        </div>
      </section>
    </div>
  )
}
