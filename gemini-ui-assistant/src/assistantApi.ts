/** Fetch wrapper for the assistant service, with timeout and friendly errors. */

import type { UIContext } from './contextBuilder'

const TIMEOUT_MS = 20000

export type AssistantReply = { answer: string; mock: boolean }

export async function askAssistant(question: string, uiContext: UIContext): Promise<AssistantReply> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  let res: Response
  try {
    res = await fetch('/assistant-api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, ui_context: uiContext }),
      signal: controller.signal,
    })
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === 'AbortError') {
      throw new Error('The assistant took too long to answer. Please try again.')
    }
    throw new Error('Could not reach the assistant. Please check that it is running.')
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    let detail = ''
    try {
      const body: unknown = await res.json()
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // Non-JSON error body — fall through to the generic message.
    }
    throw new Error(detail || 'The assistant could not answer right now. Please try again.')
  }

  return res.json() as Promise<AssistantReply>
}
