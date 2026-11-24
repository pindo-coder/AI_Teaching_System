export interface SseRequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  signal?: AbortSignal
  unavailableMessage: string
  errorFallbackMessage?: string
}

function handleUnauthorized() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('current_user')
  if (!location.pathname.startsWith('/login')) {
    location.href = '/login'
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const payload = await response.clone().json() as { detail?: string; message?: string; errors?: unknown }
    let detail = payload.detail || payload.message || ''
    if (payload.errors) {
      const validation = typeof payload.errors === 'string' ? payload.errors : JSON.stringify(payload.errors)
      detail = detail ? `${detail}（${validation}）` : validation
    }
    return detail
  } catch {
    try {
      return (await response.clone().text()).trim()
    } catch {
      return ''
    }
  }
}

function parseSseBlock(block: string): { event: string; rawData: string } | null {
  let event = ''
  const dataLines: string[] = []
  for (const rawLine of block.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(':')) continue
    if (rawLine.startsWith('event:')) {
      event = rawLine.slice(6).trim()
    } else if (rawLine.startsWith('data:')) {
      const rest = rawLine.slice(5)
      dataLines.push(rest.startsWith(' ') ? rest.slice(1) : rest)
    }
  }
  if (!event || !dataLines.length) return null
  return { event, rawData: dataLines.join('\n') }
}

export async function streamSseJson(
  path: string,
  onEvent: (event: string, data: unknown) => void,
  options: SseRequestOptions,
): Promise<void> {
  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const headers: Record<string, string> = {
    Authorization: `Bearer ${localStorage.getItem('access_token') || ''}`,
  }
  const init: RequestInit = {
    method: options.method || 'POST',
    headers,
    signal: options.signal,
  }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(options.body)
  }

  const response = await fetch(`${baseURL}${path}`, init)
  if (response.status === 401) {
    handleUnauthorized()
    throw new Error('登录状态已失效，请重新登录')
  }
  if (!response.ok || !response.body) {
    const detail = await readErrorDetail(response)
    const suffix = detail ? `：${detail}` : ''
    throw new Error(`${options.unavailableMessage}（HTTP ${response.status}${suffix}）`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const processBlock = (block: string) => {
    const parsed = parseSseBlock(block)
    if (!parsed) return
    let data: unknown
    try {
      data = JSON.parse(parsed.rawData)
    } catch {
      return
    }
    if (parsed.event === 'error') {
      const msg = typeof data === 'object' && data !== null && 'message' in data
        ? String((data as { message?: unknown }).message || '')
        : ''
      throw new Error(msg || options.errorFallbackMessage || 'AI 生成失败')
    }
    onEvent(parsed.event, data)
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      for (const block of blocks) processBlock(block)
    }
    buffer += decoder.decode()
    if (buffer.trim()) processBlock(buffer)
  } finally {
    try {
      await reader.cancel()
    } catch {
      // Stream already closed or aborted.
    }
    reader.releaseLock()
  }
}
