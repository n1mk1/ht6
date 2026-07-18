"use client";

import { useAuth0 } from "@auth0/auth0-react";
import {
  ArrowRight,
  Bot,
  Check,
  Cloud,
  Code2,
  Database,
  KeyRound,
  Loader2,
  LogIn,
  LogOut,
  Plus,
  Rocket,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { auth0Configured, clientConfig } from "./client-config";

type Health = {
  status: string;
  integrations: { auth0: boolean; mongodb: boolean; gemini: boolean };
};

type Note = {
  id: string;
  title: string;
  content: string;
  created_at: string;
};

const stack = [
  { name: "FastAPI", detail: "Typed async API", icon: Code2 },
  { name: "MongoDB Atlas", detail: "Durable document data", icon: Database },
  { name: "Auth0", detail: "SPA + API security", icon: ShieldCheck },
  { name: "Gemini", detail: "Generative AI ready", icon: Sparkles },
];

async function apiError(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  return payload?.detail ?? `Request failed with status ${response.status}`;
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-flex h-2.5 w-2.5 rounded-full ${active ? "bg-emerald-400 shadow-[0_0_0_4px_rgba(52,211,153,0.12)]" : "bg-slate-600"}`}
      aria-hidden="true"
    />
  );
}

export function Launchpad() {
  const {
    getAccessTokenSilently,
    isAuthenticated,
    isLoading: authLoading,
    loginWithRedirect,
    logout,
    user,
  } = useAuth0();
  const [health, setHealth] = useState<Health | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [notes, setNotes] = useState<Note[]>([]);
  const [noteTitle, setNoteTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState<"notes" | "ai" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`${clientConfig.apiUrl}/api/health`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await apiError(response));
        return response.json() as Promise<Health>;
      })
      .then((payload) => {
        if (active) {
          setHealth(payload);
          setBackendOnline(true);
        }
      })
      .catch(() => {
        if (active) setBackendOnline(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const authorizedFetch = useCallback(
    async (path: string, init?: RequestInit) => {
      const token = await getAccessTokenSilently();
      return fetch(`${clientConfig.apiUrl}${path}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          ...init?.headers,
        },
      });
    },
    [getAccessTokenSilently],
  );

  const loadNotes = useCallback(async () => {
    try {
      const response = await authorizedFetch("/api/notes");
      if (!response.ok) throw new Error(await apiError(response));
      setNotes(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load notes.");
    }
  }, [authorizedFetch]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const timer = window.setTimeout(() => void loadNotes(), 0);
    return () => window.clearTimeout(timer);
  }, [isAuthenticated, loadNotes]);

  async function createNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!noteTitle.trim()) return;
    setBusy("notes");
    setMessage(null);
    try {
      const response = await authorizedFetch("/api/notes", {
        method: "POST",
        body: JSON.stringify({
          title: noteTitle,
          content: "Created from the LaunchKit dashboard.",
        }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      setNoteTitle("");
      await loadNotes();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create the note.");
    } finally {
      setBusy(null);
    }
  }

  async function removeNote(noteId: string) {
    setMessage(null);
    try {
      const response = await authorizedFetch(`/api/notes/${noteId}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await apiError(response));
      setNotes((current) => current.filter((note) => note.id !== noteId));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not delete the note.");
    }
  }

  async function askGemini(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!prompt.trim()) return;
    setBusy("ai");
    setMessage(null);
    setAnswer("");
    try {
      const response = await authorizedFetch("/api/ai/generate", {
        method: "POST",
        body: JSON.stringify({ prompt }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      const payload = (await response.json()) as { text: string };
      setAnswer(payload.text);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Gemini could not complete the request.",
      );
    } finally {
      setBusy(null);
    }
  }

  const connected = isAuthenticated && backendOnline;

  return (
    <main className="min-h-screen overflow-hidden bg-[#080b10] text-slate-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_50%_-12%,rgba(255,104,47,0.18),transparent_38%),radial-gradient(circle_at_90%_52%,rgba(59,130,246,0.08),transparent_28%)]" />

      <header className="relative z-10 border-b border-white/8 bg-[#080b10]/80 backdrop-blur-xl">
        <div className="mx-auto flex h-18 max-w-7xl items-center justify-between px-5 sm:px-8">
          <a href="#top" className="flex items-center gap-3" aria-label="LaunchKit home">
            <span className="grid size-9 place-items-center rounded-xl bg-[#ff6737] text-white shadow-[0_8px_30px_rgba(255,103,55,0.28)]">
              <Rocket className="size-4.5" aria-hidden="true" />
            </span>
            <span className="font-semibold tracking-[-0.03em]">LaunchKit</span>
            <span className="hidden rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-bold tracking-[0.12em] text-slate-400 uppercase sm:inline-flex">
              Boilerplate
            </span>
          </a>

          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 text-xs text-slate-400 md:flex">
              <StatusDot active={backendOnline} />
              {backendOnline ? "API online" : "Start the API"}
            </div>
            {isAuthenticated ? (
              <button
                type="button"
                onClick={() =>
                  logout({ logoutParams: { returnTo: window.location.origin } })
                }
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3.5 text-sm font-medium transition hover:border-white/20 hover:bg-white/10"
              >
                <span className="hidden max-w-36 truncate sm:inline">
                  {user?.name ?? user?.email ?? "Account"}
                </span>
                <LogOut className="size-4" aria-hidden="true" />
              </button>
            ) : (
              <button
                type="button"
                disabled={!auth0Configured || authLoading}
                onClick={() => loginWithRedirect()}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-4 text-sm font-semibold text-slate-950 transition hover:bg-orange-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <LogIn className="size-4" aria-hidden="true" />
                Sign in
              </button>
            )}
          </div>
        </div>
      </header>

      <section
        id="top"
        className="relative z-10 mx-auto max-w-7xl px-5 pt-16 pb-10 sm:px-8 sm:pt-22"
      >
        <div className="grid items-end gap-10 lg:grid-cols-[1.08fr_0.92fr]">
          <div>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-orange-400/20 bg-orange-400/8 px-3 py-1.5 text-xs font-semibold text-orange-300">
              <Sparkles className="size-3.5" aria-hidden="true" />
              Production-shaped from day one
            </div>
            <h1 className="max-w-3xl text-5xl leading-[0.96] font-semibold tracking-[-0.055em] text-balance sm:text-7xl">
              Skip the setup.
              <span className="block text-slate-500">Start with momentum.</span>
            </h1>
            <p className="mt-7 max-w-xl text-base leading-7 text-slate-400 sm:text-lg">
              A clean full-stack foundation with authenticated requests, durable Atlas data,
              and a working Gemini flow—already connected end to end.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {stack.map(({ name, detail, icon: Icon }) => (
              <div
                key={name}
                className="rounded-2xl border border-white/8 bg-white/[0.035] p-4 transition hover:border-white/15 hover:bg-white/[0.055]"
              >
                <Icon className="mb-6 size-5 text-slate-400" aria-hidden="true" />
                <p className="text-sm font-semibold">{name}</p>
                <p className="mt-1 text-xs leading-5 text-slate-500">{detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto max-w-7xl px-5 pb-20 sm:px-8">
        {message && (
          <div
            role="alert"
            className="mb-4 rounded-xl border border-rose-400/20 bg-rose-400/8 px-4 py-3 text-sm text-rose-200"
          >
            {message}
          </div>
        )}

        <div className="overflow-hidden rounded-[26px] border border-white/10 bg-[#0d1118] shadow-2xl shadow-black/30">
          <div className="flex flex-col justify-between gap-3 border-b border-white/8 px-5 py-4 sm:flex-row sm:items-center sm:px-6">
            <div className="flex items-center gap-3">
              <span className="grid size-9 place-items-center rounded-xl border border-white/8 bg-white/5">
                <Cloud className="size-4 text-slate-400" aria-hidden="true" />
              </span>
              <div>
                <p className="text-sm font-semibold">Integration workspace</p>
                <p className="text-xs text-slate-500">Live calls to your FastAPI backend</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 text-[11px] font-medium">
              {[
                ["Auth0", Boolean(health?.integrations.auth0)],
                ["Atlas", Boolean(health?.integrations.mongodb)],
                ["Gemini", Boolean(health?.integrations.gemini)],
              ].map(([label, active]) => (
                <span
                  key={String(label)}
                  className="inline-flex items-center gap-2 rounded-full border border-white/8 bg-black/20 px-2.5 py-1.5 text-slate-400"
                >
                  <StatusDot active={Boolean(active)} /> {label}
                </span>
              ))}
            </div>
          </div>

          <div className="grid lg:grid-cols-[1.15fr_0.85fr]">
            <div className="border-b border-white/8 p-5 sm:p-7 lg:border-r lg:border-b-0">
              <div className="mb-6 flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-bold tracking-[0.15em] text-orange-300 uppercase">
                    Gemini playground
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
                    Turn an idea into a first pass.
                  </h2>
                </div>
                <Bot className="mt-1 size-5 text-slate-500" aria-hidden="true" />
              </div>

              <form onSubmit={askGemini}>
                <label htmlFor="prompt" className="sr-only">
                  Prompt for Gemini
                </label>
                <div className="rounded-2xl border border-white/10 bg-black/20 p-2 focus-within:border-orange-400/40">
                  <textarea
                    id="prompt"
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder="Draft a concise launch checklist for my new product..."
                    className="min-h-32 w-full resize-none bg-transparent p-3 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-600"
                  />
                  <div className="flex items-center justify-between border-t border-white/6 px-2 pt-2">
                    <span className="text-[11px] text-slate-600">
                      Protected FastAPI route
                    </span>
                    <button
                      type="submit"
                      disabled={!connected || busy === "ai" || !prompt.trim()}
                      className="inline-flex h-9 items-center gap-2 rounded-xl bg-[#ff6737] px-3.5 text-xs font-semibold text-white transition hover:bg-[#ff7a50] disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      {busy === "ai" ? (
                        <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <Send className="size-3.5" aria-hidden="true" />
                      )}
                      Generate
                    </button>
                  </div>
                </div>
              </form>

              <div className="mt-4 min-h-28 rounded-2xl border border-dashed border-white/10 bg-white/[0.02] p-4">
                {answer ? (
                  <p className="whitespace-pre-wrap text-sm leading-6 text-slate-300">
                    {answer}
                  </p>
                ) : (
                  <div className="flex h-20 items-center justify-center text-center text-xs leading-5 text-slate-600">
                    {isAuthenticated
                      ? "Your Gemini response will appear here."
                      : "Sign in, configure the backend, and send your first prompt."}
                  </div>
                )}
              </div>
            </div>

            <div className="p-5 sm:p-7">
              <div className="mb-6 flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-bold tracking-[0.15em] text-sky-300 uppercase">
                    Atlas notes
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
                    Prove persistence works.
                  </h2>
                </div>
                <Database className="mt-1 size-5 text-slate-500" aria-hidden="true" />
              </div>

              <form onSubmit={createNote} className="flex gap-2">
                <label htmlFor="note-title" className="sr-only">
                  New note title
                </label>
                <input
                  id="note-title"
                  value={noteTitle}
                  onChange={(event) => setNoteTitle(event.target.value)}
                  placeholder="Add a deployment note"
                  className="h-11 min-w-0 flex-1 rounded-xl border border-white/10 bg-black/20 px-3.5 text-sm outline-none placeholder:text-slate-600 focus:border-sky-400/40"
                />
                <button
                  type="submit"
                  disabled={!connected || busy === "notes" || !noteTitle.trim()}
                  className="grid size-11 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/8 transition hover:bg-white/12 disabled:cursor-not-allowed disabled:opacity-35"
                  aria-label="Add note"
                >
                  {busy === "notes" ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Plus className="size-4" aria-hidden="true" />
                  )}
                </button>
              </form>

              <div className="mt-4 space-y-2">
                {notes.length ? (
                  notes.map((note) => (
                    <article
                      key={note.id}
                      className="group flex items-center gap-3 rounded-xl border border-white/7 bg-white/[0.025] p-3.5"
                    >
                      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-sky-400/8 text-sky-300">
                        <Check className="size-3.5" aria-hidden="true" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{note.title}</p>
                        <p className="mt-0.5 text-[11px] text-slate-600">
                          Saved in MongoDB Atlas
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeNote(note.id)}
                        className="grid size-8 place-items-center rounded-lg text-slate-600 transition hover:bg-rose-400/10 hover:text-rose-300"
                        aria-label={`Delete ${note.title}`}
                      >
                        <Trash2 className="size-3.5" aria-hidden="true" />
                      </button>
                    </article>
                  ))
                ) : (
                  <div className="grid min-h-36 place-items-center rounded-xl border border-dashed border-white/10 text-center">
                    <div>
                      <KeyRound className="mx-auto size-5 text-slate-600" aria-hidden="true" />
                      <p className="mt-3 text-xs text-slate-500">
                        {isAuthenticated
                          ? "Create your first Atlas-backed note."
                          : "Protected data appears after sign-in."}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {[
            [
              "01",
              "Copy both env files",
              "Frontend values stay public; API secrets remain server-side.",
            ],
            [
              "02",
              "Configure the three services",
              "Use one Auth0 audience in both applications, then add Atlas and Gemini keys.",
            ],
            [
              "03",
              "Run the checks",
              "Backend tests and the frontend production build are included.",
            ],
          ].map(([number, title, detail]) => (
            <div
              key={number}
              className="group rounded-2xl border border-white/8 bg-white/[0.025] p-5"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-slate-600">{number}</span>
                <ArrowRight
                  className="size-4 text-slate-700 transition group-hover:translate-x-1 group-hover:text-orange-300"
                  aria-hidden="true"
                />
              </div>
              <h3 className="mt-8 text-sm font-semibold">{title}</h3>
              <p className="mt-2 text-xs leading-5 text-slate-500">{detail}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
