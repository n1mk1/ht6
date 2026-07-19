import { AlertCircle, LoaderCircle } from 'lucide-react'

export function LoadingState({ label = 'Loading sessions' }: { label?: string }) {
  return (
    <div className="state-block" role="status">
      <LoaderCircle className="spin" size={20} />
      <span>{label}</span>
    </div>
  )
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="state-block state-error" role="alert">
      <AlertCircle size={20} />
      <div>
        <strong>Could not load this view</strong>
        <p>{message}</p>
      </div>
      {retry && <button onClick={retry}>Retry</button>}
    </div>
  )
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="empty-state">
      <span className="empty-mark" aria-hidden="true" />
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  )
}

