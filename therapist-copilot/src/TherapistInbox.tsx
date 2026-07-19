import { useCallback, useEffect, useState } from 'react'
import './TherapistInbox.css'

const POLL_MS = 4000

type Priority = 'needs_attention' | 'review' | 'routine'
type ReviewStatus = 'pending' | 'approved' | 'edited'

type MetricDelta = {
  label: string
  current: number
  participant_avg: number
  delta: number
}

export type ReviewItem = {
  id: string
  run_id: string
  participant_id: string
  received_at: string
  priority: Priority
  quality_verdict: 'unusable' | 'usable_with_warnings' | 'clean'
  quality_reasons: string[]
  deltas: MetricDelta[]
  sessions_compared: number
  draft_note: string
  note_is_mock: boolean
  decision_log: string[]
  status: ReviewStatus
}

const PRIORITY_META: Record<Priority, { label: string; className: string }> = {
  needs_attention: { label: 'Needs attention', className: 'inbox-badge-attention' },
  review: { label: 'Review', className: 'inbox-badge-review' },
  routine: { label: 'Routine', className: 'inbox-badge-routine' },
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
}

function ReviewCard({ item, onAction }: { item: ReviewItem; onAction: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [noteDraft, setNoteDraft] = useState(item.draft_note)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const meta = PRIORITY_META[item.priority]

  async function post(path: 'approve' | 'edit', body?: { note: string }) {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`/copilot-api/reviews/${item.id}/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
      if (!res.ok) throw new Error(`Request failed (${res.status})`)
      onAction()
      setEditing(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Request failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={`inbox-card${item.status !== 'pending' ? ' inbox-card-done' : ''}`}>
      <button
        type="button"
        className="inbox-card-head"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span className={`inbox-badge ${meta.className}`}>{meta.label}</span>
        <span className="inbox-participant">{item.participant_id}</span>
        <span className="inbox-time">{fmtTime(item.received_at)}</span>
        <span className="inbox-status">
          {item.status === 'pending'
            ? 'Awaiting review'
            : item.status === 'approved'
              ? 'Approved ✓'
              : 'Edited ✓'}
        </span>
      </button>

      {expanded && (
        <div className="inbox-card-body">
          <h4>What the copilot did</h4>
          <ol className="inbox-log">
            {item.decision_log.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>

          {item.deltas.length > 0 && (
            <>
              <h4>Compared with their recent sessions</h4>
              <table className="inbox-deltas">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>This session</th>
                    <th>Their average</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {item.deltas.map((d) => (
                    <tr key={d.label}>
                      <td>{d.label}</td>
                      <td>{d.current}</td>
                      <td>{d.participant_avg}</td>
                      <td>{d.delta > 0 ? `+${d.delta}` : d.delta}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h4>
            Draft note
            {item.note_is_mock && <span className="inbox-mock"> (template — no API key set)</span>}
          </h4>
          {editing ? (
            <textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              rows={8}
              aria-label="Edit draft note"
            />
          ) : (
            <pre className="inbox-note">{item.draft_note}</pre>
          )}

          {error && <p className="inbox-error">{error}</p>}

          {item.status === 'pending' && (
            <div className="inbox-actions">
              {editing ? (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void post('edit', { note: noteDraft })}
                  >
                    Save &amp; approve
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => setEditing(false)}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <button type="button" disabled={busy} onClick={() => void post('approve')}>
                    Approve note
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => setEditing(true)}
                  >
                    Edit
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  )
}

export default function TherapistInbox() {
  const [items, setItems] = useState<ReviewItem[] | null>(null)
  const [serviceUp, setServiceUp] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/copilot-api/inbox')
      if (!res.ok) throw new Error()
      setItems((await res.json()) as ReviewItem[])
      setServiceUp(true)
    } catch {
      setServiceUp(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(t)
  }, [refresh])

  const pending = items?.filter((i) => i.status === 'pending').length ?? 0

  return (
    <section className="panel inbox">
      <div className="inbox-head">
        <h2>Therapist Inbox</h2>
        {serviceUp && items && (
          <span className="inbox-count">
            {pending === 0 ? 'All caught up' : `${pending} awaiting review`}
          </span>
        )}
      </div>
      <p className="inbox-sub">
        The copilot triages each incoming session, compares it with the participant's history,
        and drafts a note for your approval. Nothing is published without your sign-off.
      </p>

      {!serviceUp && (
        <p className="inbox-error">
          Copilot service not reachable — start it with{' '}
          <code>uvicorn server.main:app --port 8003</code> in <code>therapist-copilot/</code>.
        </p>
      )}

      {serviceUp && items && items.length === 0 && (
        <p className="inbox-empty">
          No sessions processed yet — new runs appear here automatically.
        </p>
      )}

      {serviceUp && items && items.length > 0 && (
        <ul className="inbox-list">
          {items.map((item) => (
            <ReviewCard key={item.id} item={item} onAction={() => void refresh()} />
          ))}
        </ul>
      )}
    </section>
  )
}
