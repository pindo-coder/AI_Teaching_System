import type { AgentStreamHandlers } from './agentEventStream'

type RunState = { id: number; status: string }
type Timer = ReturnType<typeof setTimeout>
interface MonitorSession {
  id: number
  controller: AbortController
  stream?: AbortController
  pollTimer?: Timer
  reconnectTimer?: Timer
  refreshPromise?: Promise<void>
  refreshAgain: boolean
  failures: number
  reconnectDelay: number
}

/** SSE gives low-latency change notifications; serialized GETs are canonical.
 * Polling remains active even if the stream hangs or a proxy buffers events.
 * This avoids a delayed SSE snapshot overwriting a newer HTTP/terminal state.
 * Only reads state: never creates, retries, cancels or publishes a task.
 */
export function createAgentRunMonitor<T extends RunState>(options: {
  fetchRun: (id: number, signal: AbortSignal) => Promise<T>
  stream: (id: number, handlers: AgentStreamHandlers<T>, signal: AbortSignal) => Promise<void>
  onSnapshot: (run: T) => void
  onError?: (error: unknown, fatal: boolean) => void
  pollIntervalMs?: number
}) {
  let session: MonitorSession | undefined
  const interval = options.pollIntervalMs ?? 5000
  const live = (value: MonitorSession) => session === value && !value.controller.signal.aborted
  function stop() {
    const previous = session
    session = undefined
    if (!previous) return
    clearTimeout(previous.pollTimer)
    clearTimeout(previous.reconnectTimer)
    previous.controller.abort()
    previous.stream?.abort()
  }
  function refresh(value: MonitorSession): Promise<void> {
    if (!live(value)) return Promise.resolve()
    if (value.refreshPromise) {
      value.refreshAgain = true
      return value.refreshPromise
    }
    clearTimeout(value.pollTimer)
    const pending = (async () => {
      do {
        value.refreshAgain = false
        try {
          const run = await options.fetchRun(value.id, value.controller.signal)
          if (!live(value)) return
          if (run.id !== value.id) throw new Error('任务进度与当前任务不匹配')
          value.failures = 0
          options.onSnapshot(run)
          if (!['queued', 'running'].includes(run.status)) {
            if (live(value)) stop()
            return
          }
        } catch (error) {
          if (!live(value)) return
          const status = (error as { response?: { status?: number }; status?: number })?.response?.status
            ?? (error as { status?: number })?.status
          const fatal = status === 401 || status === 403 || status === 404
          value.failures += 1
          if (fatal) stop()
          options.onError?.(error, fatal)
          // Network failures back off; change notifications cannot spin a
          // failed HTTP request in a tight loop.
          break
        }
      } while (live(value) && value.refreshAgain)
    })()
    value.refreshPromise = pending
    void pending.finally(() => {
      if (value.refreshPromise === pending) value.refreshPromise = undefined
      if (live(value)) {
        if (value.refreshAgain && !value.failures) void refresh(value)
        else {
          const delay = Math.min(30_000, interval * 2 ** Math.min(value.failures, 3))
          value.pollTimer = setTimeout(() => { void refresh(value) }, delay)
        }
      }
    }).catch(() => undefined)
    return pending
  }
  function connect(value: MonitorSession) {
    if (!live(value) || value.stream) return
    clearTimeout(value.reconnectTimer)
    const controller = new AbortController()
    value.stream = controller
    const started = Date.now()
    void (async () => {
      try {
        await options.stream(value.id, {
          // Treat the stream as an invalidation signal, not another writer.
          // Slow/buffered old snapshots can never roll the UI back.
          onSnapshot: () => { if (live(value) && !value.failures) void refresh(value) },
          onDone: () => { if (live(value)) void refresh(value) },
        }, controller.signal)
      } catch {
        // The read-only fallback decides whether this is temporary, a missing
        // task, or an expired login. A broken stream is not a failed AI job.
      } finally {
        if (value.stream === controller) value.stream = undefined
        if (live(value)) {
          if (!value.failures) void refresh(value)
          if (Date.now() - started >= 30_000) value.reconnectDelay = 1000
          value.reconnectTimer = setTimeout(() => connect(value), value.reconnectDelay)
          value.reconnectDelay = Math.min(30_000, value.reconnectDelay * 2)
        }
      }
    })()
  }
  return {
    start(id: number) {
      if (session?.id === id && live(session)) return
      stop()
      const value: MonitorSession = { id, controller: new AbortController(), refreshAgain: false, failures: 0, reconnectDelay: 1000 }
      session = value
      void refresh(value)
      connect(value)
    },
    refresh() {
      if (session) {
        void refresh(session)
        connect(session)
      }
    },
    stop,
  }
}
