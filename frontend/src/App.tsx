import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  CalendarDays,
  ChevronRight,
  CircleUserRound,
  GitCompareArrows,
  LayoutDashboard,
  LogOut,
  Menu,
  X,
} from 'lucide-react'
import { api } from './api'
import { ComparisonView } from './components/ComparisonView'
import { LoginScreen } from './components/LoginScreen'
import { EmptyState, ErrorState, LoadingState } from './components/States'
import { SessionView } from './components/SessionView'
import { TrendChart } from './components/TrendChart'
import { formatDate, titleCase } from './format'
import type { PairComparison, Session, TrendPoint, User } from './types'

type View = 'overview' | 'history' | 'compare'
const sessionKey = (session: Session) => `${session.device_id}::${session.session_id}`

function App() {
  const [users, setUsers] = useState<User[]>([])
  const [selectedUser, setSelectedUser] = useState<number | null>(null)
  const [authenticated, setAuthenticated] = useState(false)
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [latest, setLatest] = useState<Session | null>(null)
  const [trends, setTrends] = useState<TrendPoint[]>([])
  const [selectedSession, setSelectedSession] = useState<Session | null>(null)
  const [view, setView] = useState<View>('overview')
  const [loadingData, setLoadingData] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [referenceId, setReferenceId] = useState('')
  const [currentId, setCurrentId] = useState('')
  const [comparison, setComparison] = useState<PairComparison | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const login = useCallback(async (username: string) => {
    setLoginLoading(true)
    setLoginError(null)
    try {
      const { user } = await api.resolveUser(username)
      window.localStorage.setItem('praxis.username', user.username)
      setUsers([user])
      setSelectedUser(user.id)
      setAuthenticated(true)
    } catch (reason) {
      setLoginError(reason instanceof Error ? reason.message : 'The API is unavailable.')
    } finally {
      setLoginLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selectedUser == null) return
    let cancelled = false
    setLoadingData(true)
    setError(null)
    Promise.all([api.sessions(selectedUser), api.trends(selectedUser)])
      .then(async ([history, trendData]) => {
        const current = history.length ? await api.latest(selectedUser) : null
        if (cancelled) return
        setSessions(history)
        setLatest(current)
        setTrends(trendData.series)
        setSelectedSession(null)
        setReferenceId(history[1] ? sessionKey(history[1]) : history[0] ? sessionKey(history[0]) : '')
        setCurrentId(history[0] ? sessionKey(history[0]) : '')
        setComparison(null)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Sessions could not be loaded.')
      })
      .finally(() => { if (!cancelled) setLoadingData(false) })
    return () => { cancelled = true }
  }, [selectedUser, reloadKey])

  const activeUser = users.find((user) => user.id === selectedUser) ?? null
  const selectedForComparison = useMemo(() => new Map(sessions.map((session) => [sessionKey(session), session])), [sessions])

  async function openSession(session: Session) {
    setLoadingData(true)
    setError(null)
    try {
      const detail = await api.session(session.device_id, session.session_id)
      setSelectedSession(detail)
      setView('history')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'This session is invalid or unavailable.')
    } finally {
      setLoadingData(false)
    }
  }

  async function compareRuns() {
    const reference = selectedForComparison.get(referenceId)
    const current = selectedForComparison.get(currentId)
    if (!reference || !current) return
    if (referenceId === currentId) {
      setComparisonError('Choose two different runs.')
      return
    }
    setComparisonLoading(true)
    setComparisonError(null)
    setComparison(null)
    try {
      setComparison(await api.comparison(reference, current))
    } catch (reason) {
      setComparisonError(reason instanceof Error ? reason.message : 'These runs could not be compared.')
    } finally {
      setComparisonLoading(false)
    }
  }

  function switchUser() {
    setAuthenticated(false)
    setSelectedUser(null)
    setUsers([])
    setSessions([])
    setLatest(null)
    setTrends([])
    setError(null)
    setView('overview')
  }

  const navigation = [
    { id: 'overview' as const, label: 'Overview', icon: LayoutDashboard },
    { id: 'history' as const, label: 'Session history', icon: CalendarDays },
    { id: 'compare' as const, label: 'Compare runs', icon: GitCompareArrows },
  ]

  if (!authenticated) {
    return (
      <LoginScreen
        initialUsername={window.localStorage.getItem('praxis.username') ?? ''}
        loading={loginLoading}
        error={loginError}
        onSubmit={(username) => void login(username)}
      />
    )
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark"><Activity size={19} /></div>
          <div><strong>Praxis</strong><span>Performance console</span></div>
          <button className="icon-button mobile-only" title="Close navigation" onClick={() => setSidebarOpen(false)}><X size={19} /></button>
        </div>
        <nav aria-label="Primary navigation">
          {navigation.map((item) => (
            <button key={item.id} className={view === item.id ? 'nav-active' : ''} onClick={() => { setView(item.id); setSidebarOpen(false) }}>
              <item.icon size={18} />{item.label}
            </button>
          ))}
        </nav>
        <div className="user-section">
          <div className="sidebar-label"><CircleUserRound size={14} /> Current participant</div>
          {users.map((user) => (
            <button key={user.id} className={`user-button ${selectedUser === user.id ? 'user-active' : ''}`} onClick={() => { setSelectedUser(user.id); setView('overview'); setSidebarOpen(false) }}>
              <span className="avatar">{(user.display_name ?? user.username).slice(0, 2).toUpperCase()}</span>
              <span><strong>{user.display_name ?? user.username}</strong><small>{user.session_count} session{user.session_count === 1 ? '' : 's'}</small></span>
              <ChevronRight size={15} />
            </button>
          ))}
          <button className="switch-user" onClick={switchUser}><LogOut size={16} /> Switch user</button>
        </div>
        <div className="prototype-note"><span /> Prototype task-performance measures. Not validated clinical metrics.</div>
      </aside>
      {sidebarOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />}

      <main>
        <header className="topbar">
          <button className="icon-button menu-button" title="Open navigation" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span>Praxis</span><ChevronRight size={14} /><strong>{navigation.find((item) => item.id === view)?.label}</strong></div>
          <div className="api-status"><span /> API connected</div>
        </header>

        <div className="content">
          {error && !loadingData && <ErrorState message={error} retry={() => setReloadKey((value) => value + 1)} />}
          {loadingData && <LoadingState />}
          {!loadingData && !error && activeUser && (
            <>
              <div className="page-heading">
                <div>
                  <span className="section-kicker"><CircleUserRound size={14} /> Participant profile</span>
                  <h1>{activeUser.display_name ?? activeUser.username}</h1>
                  <p>{activeUser.session_count} recorded session{activeUser.session_count === 1 ? '' : 's'} / Last activity {formatDate(activeUser.latest_session_at)}</p>
                </div>
                <div className="profile-id">ID {activeUser.username}</div>
              </div>

              {view === 'overview' && latest && <><SessionView session={latest} latest /><TrendChart data={trends} /></>}
              {view === 'overview' && !latest && <EmptyState title="No sessions yet" message="Use this same username on QNX. Completed runs will appear here automatically." />}

              {view === 'history' && (
                <div className="history-layout">
                  <section className="history-list panel">
                    <div className="panel-heading"><div><span className="section-kicker">All runs</span><h2>Session history</h2></div><span>{sessions.length} total</span></div>
                    {sessions.map((session) => (
                      <button key={sessionKey(session)} className={selectedSession?.id === session.id ? 'history-active' : ''} onClick={() => void openSession(session)}>
                        <span className="history-date"><strong>{formatDate(session.created_at)}</strong><small>{session.session_id}</small></span>
                        <span className="history-task">{titleCase(session.task.type)}<small>{session.task.version}</small></span>
                        <span className="score-pair"><b>{session.scores.accuracy ?? '-'}</b><small>ACC</small></span>
                        <span className="score-pair"><b>{session.scores.stability ?? '-'}</b><small>STB</small></span>
                        <ChevronRight size={16} />
                      </button>
                    ))}
                  </section>
                  <section className="history-detail">
                    {selectedSession ? <SessionView session={selectedSession} /> : <EmptyState title="Select a session" message="Choose a run to inspect its measurements, quality, trace, and analysis status." />}
                  </section>
                </div>
              )}

              {view === 'compare' && (
                <ComparisonView sessions={sessions} comparison={comparison} loading={comparisonLoading} error={comparisonError} referenceId={referenceId} currentId={currentId} onReference={setReferenceId} onCurrent={setCurrentId} onCompare={() => void compareRuns()} />
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
