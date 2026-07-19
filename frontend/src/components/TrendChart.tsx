import { Activity } from 'lucide-react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatDate } from '../format'
import type { TrendPoint } from '../types'
import { EmptyState } from './States'

export function TrendChart({ data }: { data: TrendPoint[] }) {
  if (!data.length) {
    return <EmptyState title="No trend yet" message="Trend lines appear after the first compatible session." />
  }
  const chartData = data.map((point) => ({ ...point, label: formatDate(point.created_at) }))
  return (
    <section className="panel trend-panel" aria-labelledby="trend-title">
      <div className="panel-heading">
        <div>
          <span className="section-kicker"><Activity size={14} /> Across sessions</span>
          <h2 id="trend-title">Performance trend</h2>
        </div>
        <div className="legend-note">Version-matched runs only when compared</div>
      </div>
      <div className="chart-wrap" data-testid="trend-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 10, right: 8, bottom: 4, left: -22 }}>
            <CartesianGrid stroke="#e5e7e2" vertical={false} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#68706a', fontSize: 12 }} />
            <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: '#68706a', fontSize: 12 }} />
            <Tooltip contentStyle={{ border: '1px solid #d9ddd7', borderRadius: 6, boxShadow: '0 8px 24px rgba(27,35,30,.08)' }} />
            <Legend iconType="plainline" />
            <Line type="monotone" name="Accuracy" dataKey="accuracy" stroke="#167356" strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} />
            <Line type="monotone" name="Stability" dataKey="stability" stroke="#2e64a1" strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

