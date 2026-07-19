export function formatDate(value: string | null | undefined, includeTime = false): string {
  if (!value) return 'Not available'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Invalid date'
  return new Intl.DateTimeFormat('en-CA', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    ...(includeTime ? { hour: 'numeric', minute: '2-digit' } : {}),
  }).format(date)
}

export function metric(value: number | null | undefined, suffix = '', digits = 1): string {
  return value == null ? 'Unavailable' : `${value.toFixed(digits)}${suffix}`
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return 'Unavailable'
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export const metricLabels: Record<string, { label: string; suffix: string }> = {
  accuracy_score: { label: 'Accuracy score', suffix: '' },
  stability_score: { label: 'Stability score', suffix: '' },
  coverage_pct: { label: 'Coverage', suffix: '%' },
  completion_time_seconds: { label: 'Completion time', suffix: ' s' },
  mean_dev_mm: { label: 'Mean deviation', suffix: ' mm' },
  max_dev_mm: { label: 'Max deviation', suffix: ' mm' },
  rms_dev_mm: { label: 'RMS deviation', suffix: ' mm' },
  tremor_rms_deg_s: { label: 'Tremor RMS', suffix: ' deg/s' },
  gyro_rms_deg_s: { label: 'Gyro RMS', suffix: ' deg/s' },
  peak_angular_velocity_deg_s: { label: 'Peak angular velocity', suffix: ' deg/s' },
}

