import { Activity, ArrowRight, UserRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'

type Props = {
  initialUsername: string
  loading: boolean
  error: string | null
  onSubmit: (username: string) => void
}

export function LoginScreen({ initialUsername, loading, error, onSubmit }: Props) {
  const [username, setUsername] = useState(initialUsername)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const value = username.trim()
    if (value) onSubmit(value)
  }

  return (
    <main className="login-page">
      <section className="login-intro">
        <div className="login-brand">
          <span><Activity size={21} /></span>
          <strong>Praxis</strong>
        </div>
        <div className="login-copy">
          <span className="section-kicker">Praxis session record</span>
          <h1>Review your movement sessions over time.</h1>
          <p>View measurements from each tracing session and compare your results across visits.</p>
        </div>
        <div className="login-signal" aria-hidden="true">
          <span /><span /><span /><span /><span /><span /><span />
        </div>
        <p className="login-boundary">For monitoring task performance only. Praxis does not provide a diagnosis or medical advice.</p>
      </section>
      <section className="login-entry" aria-labelledby="login-title">
        <form className="login-form" onSubmit={submit}>
          <div className="login-icon"><UserRound size={22} /></div>
          <span className="section-kicker">Participant record</span>
          <h2 id="login-title">Enter your username</h2>
          <p>Enter the same username used on the Praxis device. This connects each completed session to your record.</p>
          <label htmlFor="praxis-username">Username</label>
          <input
            id="praxis-username"
            name="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck="false"
            maxLength={120}
            required
            autoFocus
            placeholder="Your username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            aria-describedby={error ? 'login-error' : 'username-help'}
          />
          <small id="username-help">Ask your clinician or session facilitator if you are unsure which username to use.</small>
          {error && <div id="login-error" className="login-error" role="alert">{error}</div>}
          <button className="login-button" type="submit" disabled={loading || !username.trim()}>
            {loading ? 'Opening record...' : 'View my sessions'}
            {!loading && <ArrowRight size={17} />}
          </button>
        </form>
      </section>
    </main>
  )
}
