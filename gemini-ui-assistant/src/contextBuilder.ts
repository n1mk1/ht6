/**
 * Builds the controlled UI-context object sent to the assistant service.
 *
 * Only labels, values, help text, and action descriptions go in — never the
 * DOM, raw usernames, tokens, camera footage, or IMU streams. The server
 * applies a second sanitization pass, but privacy starts here.
 */

import type { Session } from '../../frontend/src/types'

export type UISection = { id: string; label: string; description: string }
export type UIMetric = { label: string; value: string; help_text: string }
export type UIAction = { label: string; description: string }
export type UIContext = {
  page: string
  page_title: string
  visible_sections: UISection[]
  visible_metrics: UIMetric[]
  available_actions: UIAction[]
}

type View = 'overview' | 'history' | 'compare' | 'inbox'

type BuilderInput = {
  view: View
  sessionCount: number
  latest?: Session | null
  selectedSession?: Session | null
}

const VIEW_TITLES: Record<View, string> = {
  overview: 'Participant Overview',
  history: 'Session History',
  compare: 'Compare Runs',
  inbox: 'Therapist Inbox',
}

function score(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value)
}

function sessionMetrics(session: Session, prefix: string): UIMetric[] {
  const metrics: UIMetric[] = []
  const accuracy = score(session.scores.accuracy)
  if (accuracy) {
    metrics.push({
      label: `${prefix} Accuracy`,
      value: accuracy,
      help_text:
        'How closely the traced movement followed the reference path on this task (0 to 100).',
    })
  }
  const stability = score(session.scores.stability)
  if (stability) {
    metrics.push({
      label: `${prefix} Stability`,
      value: stability,
      help_text: 'How steady the hand movement was during this task (0 to 100).',
    })
  }
  const coverage = session.metrics.coverage_pct
  if (coverage !== null && coverage !== undefined) {
    metrics.push({
      label: `${prefix} Coverage`,
      value: `${coverage}%`,
      help_text: 'How much of the reference path was traced.',
    })
  }
  const duration = session.metrics.completion_time_seconds
  if (duration !== null && duration !== undefined) {
    metrics.push({
      label: `${prefix} Duration`,
      value: `${duration} seconds`,
      help_text: 'How long this tracing attempt took.',
    })
  }
  return metrics
}

export function buildUiContext({ view, sessionCount, latest, selectedSession }: BuilderInput): UIContext {
  const sections: UISection[] = []
  const metrics: UIMetric[] = []
  const actions: UIAction[] = [
    {
      label: 'Overview',
      description: 'Shows the most recent session and performance trends across sessions.',
    },
    {
      label: 'Session history',
      description: 'Lists every recorded session; selecting one shows its details.',
    },
    {
      label: 'Compare runs',
      description: 'Opens a comparison between two selected sessions.',
    },
    {
      label: 'Switch user',
      description: 'Signs out and returns to the participant login screen.',
    },
  ]

  if (view === 'overview') {
    sections.push({
      id: 'latest-session',
      label: 'Latest Session',
      description: 'Shows the most recent path-tracing attempt with its measurements.',
    })
    sections.push({
      id: 'trend-chart',
      label: 'Performance Trends',
      description:
        'A chart showing how task measurements changed across the participant’s own sessions.',
    })
    if (latest) metrics.push(...sessionMetrics(latest, 'Latest session'))
  }

  if (view === 'history') {
    sections.push({
      id: 'session-list',
      label: 'Session History',
      description: `A list of ${sessionCount} recorded session${sessionCount === 1 ? '' : 's'}, newest first. Selecting one shows its details.`,
    })
    if (selectedSession) {
      sections.push({
        id: 'session-detail',
        label: 'Session Details',
        description:
          'Measurements and the trace drawing for the selected session: the blue line is the reference path, the red line is the traced attempt.',
      })
      metrics.push(...sessionMetrics(selectedSession, 'Selected session'))
      const warnings = selectedSession.quality.warnings ?? []
      if (warnings.length > 0) {
        sections.push({
          id: 'warnings',
          label: 'Warnings',
          description: `This session has data-quality notes: ${warnings.join(', ')}. These describe how the session was recorded, not the participant's health.`,
        })
      }
    }
  }

  if (view === 'inbox') {
    sections.push({
      id: 'therapist-inbox',
      label: 'Therapist Inbox',
      description:
        'A worklist for the therapist. Each incoming session was checked for data quality, compared with the participant’s history, and given a draft note awaiting the therapist’s approval.',
    })
  }

  if (view === 'compare') {
    sections.push({
      id: 'comparison',
      label: 'Compare Runs',
      description:
        'Compares two of the participant’s own sessions side by side, showing how each measurement changed between them.',
    })
    actions.push({
      label: 'Compare',
      description: 'Runs the comparison between the two selected sessions.',
    })
  }

  return {
    page: view,
    page_title: VIEW_TITLES[view],
    visible_sections: sections,
    visible_metrics: metrics,
    available_actions: actions,
  }
}
