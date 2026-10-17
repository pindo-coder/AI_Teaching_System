/** Abortable SSE transport. Reconnection belongs to the run monitor, not here. */
export class AgentEventStreamError extends Error {
  status?: number
  constructor(message: string, status?: number) {
    super(message)
    this.name = 'AgentEventStreamError'
    this.status = status
  }
}

export interface AgentStreamHandlers<T> {
  onSnapshot: (run: T) => void | Promise<void>
  onDone?: () => void | Promise<void>
}

export async function streamAgentEvents<T>(options: {
  url: string
  token: string
  handlers: AgentStreamHandlers<T>
  signal?: AbortSignal
  idleTimeoutMs?: number
}): Promise<void> {
  const controller = new AbortController()
  const abort = () => controller.abort(options.signal?.reason)
  if (options.signal?.aborted) abort()
  else options.signal?.addEventListener('abort', abort, { once: true })
  let timedOut = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  const armIdleTimer = () => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, options.idleTimeoutMs ?? 30_000)
  }
  try {
    armIdleTimer()
    const response = await fetch(options.url, {
      headers: { Authorization: `Bearer ${options.token}` },
      signal: controller.signal,
      cache: 'no-store',
    })
    if (!response.ok || !response.body) throw new AgentEventStreamError('智能任务进度服务暂时不可用', response.status)
    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const dispatch = async (block: string): Promise<boolean> => {
      let event = ''
      const lines: string[] = []
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''))
      }
      if (!event || !lines.length) return false // heartbeat/comments
      let data
      try { data = JSON.parse(lines.join('\n')) }
      catch { throw new AgentEventStreamError('智能任务进度数据异常，请重新同步') }
      if (event === 'snapshot') await options.handlers.onSnapshot(data as T)
      if (event === 'error') throw new AgentEventStreamError('智能任务进度读取失败，请重新同步')
      if (event === 'done') {
        await options.handlers.onDone?.()
        return true
      }
      return false
    }
    while (true) {
      const { value, done } = await reader.read()
      if (done) {
        buffer += decoder.decode()
        if (buffer.trim() && await dispatch(buffer)) return
        // EOF is not task completion. Some proxies end idle streams without
        // an error; callers must refresh/reconnect rather than silently stop.
        throw new AgentEventStreamError('智能任务进度连接已断开')
      }
      armIdleTimer()
      buffer += decoder.decode(value, { stream: true })
      if (buffer.length > 2 * 1024 * 1024) throw new AgentEventStreamError('智能任务进度消息超过限制')
      let boundary: RegExpExecArray | null
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        if (await dispatch(block)) return
      }
    }
  } catch (error) {
    if (timedOut) throw new AgentEventStreamError('智能任务进度连接超时')
    throw error
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', abort)
    controller.abort()
    if (reader) {
      await reader.cancel().catch(() => undefined)
      reader.releaseLock()
    }
  }
}
