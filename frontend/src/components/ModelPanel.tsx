import { AlertTriangle, BrainCircuit, Clock3, CircleOff, Sparkles } from 'lucide-react'
import { titleCase } from '../format'
import type { ModelResult } from '../types'

export function ModelPanel({ result }: { result: ModelResult | null }) {
  const status = result?.status ?? 'pending'
  const icon = status === 'completed' ? <Sparkles size={17} /> : status === 'error' ? <AlertTriangle size={17} /> : status === 'unavailable' ? <CircleOff size={17} /> : <Clock3 size={17} />
  const label = status === 'completed' ? titleCase(result?.overall_pattern) : titleCase(status)
  return (
    <section className={`model-panel model-${status}`} aria-labelledby="model-title">
      <div className="model-title-row">
        <span className="section-kicker"><BrainCircuit size={14} /> FreeSOLO session analysis</span>
        <span className="status-chip">{icon}{label}</span>
      </div>
      <h3 id="model-title">
        {status === 'completed' ? `Task pattern: ${label}` : status === 'pending' ? 'Analysis is pending' : status === 'error' ? 'Analysis could not complete' : 'Analysis unavailable'}
      </h3>
      {status === 'completed' && result?.adapter === 'development_mock' && (
        <p className="warning-copy">Development simulation only. No production model analysis was generated.</p>
      )}
      {status === 'completed' && result?.result?.observations?.map((observation) => (
        <p key={observation.statement}>{observation.statement}</p>
      ))}
      {status === 'completed' && result?.result?.conflicts_or_limitations?.map((limitation) => (
        <p className="clinical-note" key={limitation}>{limitation}</p>
      ))}
      {status === 'completed' && result?.result?.possible_next_step && (
        <p><strong>Suggested review step:</strong> {result.result.possible_next_step}</p>
      )}
      {status === 'unavailable' && (
        <p>The source session does not yet satisfy the deployed model contract. Raw measurements and deterministic comparisons remain available.</p>
      )}
      {status === 'error' && <p>{result?.error_detail ?? 'The model service returned an invalid or unavailable response.'}</p>}
      {status === 'pending' && <p>The session is stored. This result will update after the model adapter finishes.</p>}
      <p className="clinical-note">This is a model-generated description of measured task performance, not a diagnosis or validated clinical deterioration.</p>
      {result?.model_version && <span className="model-version">Model {result.model_version}</span>}
    </section>
  )
}
