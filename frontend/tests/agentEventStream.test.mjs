import assert from 'node:assert/strict'
import { test } from 'node:test'
import { streamAgentEvents } from '../src/utils/agentEventStream.ts'

const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve() }
function streamResponse(chunks) {
  return new Response(new ReadableStream({ start(controller) {
    for (const chunk of chunks) controller.enqueue(chunk)
    controller.close()
  } }), { headers: { 'content-type': 'text/event-stream' } })
}
const bytes = text => new TextEncoder().encode(text)
function options(extra = {}) {
  return { url: 'http://localhost/api/v1/agent/runs/1/events', token: 'test-not-a-real-key',
    handlers: { onSnapshot() {} }, ...extra }
}

test('SSE handles UTF-8 split bytes, CRLF, multi-line JSON, heartbeat and awaited done', async t => {
  const source = bytes(': keep-alive\r\n\r\nevent: snapshot\r\ndata: {"id":1,\r\ndata: "title":"中文进度"}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n')
  const chunks = Array.from(source, value => Uint8Array.of(value))
  t.mock.method(globalThis, 'fetch', async () => streamResponse(chunks))
  const snapshots = [], finished = []
  await streamAgentEvents(options({ handlers: {
    onSnapshot: run => snapshots.push(run),
    onDone: async () => { await Promise.resolve(); finished.push(true) },
  } }))
  assert.deepEqual(snapshots, [{ id: 1, title: '中文进度' }])
  assert.deepEqual(finished, [true])
})

test('EOF without a done event is a connection failure, not silent task completion', async t => {
  t.mock.method(globalThis, 'fetch', async () => streamResponse([bytes('event: snapshot\ndata: {"id":1}\n\n')]))
  let done = false, snapshots = 0
  await assert.rejects(streamAgentEvents(options({ handlers: {
    onSnapshot: () => { snapshots++ }, onDone: () => { done = true },
  } })), /连接已断开/)
  assert.equal(snapshots, 1)
  assert.equal(done, false)
})

test('an explicit trailing done event is accepted even without its final blank line', async t => {
  t.mock.method(globalThis, 'fetch', async () => streamResponse([bytes('event: done\ndata: {}')]))
  let done = false
  await streamAgentEvents(options({ handlers: { onSnapshot() {}, onDone: () => { done = true } } }))
  assert.equal(done, true)
})

test('HTTP errors retain status for the monitoring/authentication policy', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('not authorized', { status: 401 }))
  await assert.rejects(streamAgentEvents(options()), error => error.status === 401)
})

test('malformed frames fail with a safe message rather than displaying raw private data', async t => {
  t.mock.method(globalThis, 'fetch', async () => streamResponse([bytes('event: snapshot\ndata: private-invalid-json\n\n')]))
  await assert.rejects(streamAgentEvents(options()), error => /数据异常/.test(error.message) && !error.message.includes('private-invalid-json'))
})

function abortableFetch(t, state) {
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    state.signal = init.signal
    return new Response(new ReadableStream({
      start(controller) {
        state.controller = controller
        init.signal.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')), { once: true })
      },
      cancel() { state.cancelled = true },
    }))
  })
}

test('stalled reads time out and release their connection instead of hanging indefinitely', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const state = {}
  abortableFetch(t, state)
  const pending = streamAgentEvents(options({ idleTimeoutMs: 1000 }))
  const rejected = assert.rejects(pending, /连接超时/)
  await flush()
  t.mock.timers.tick(1000)
  await rejected
  assert.equal(state.signal.aborted, true)
})

test('heartbeat bytes reset the transport idle timeout without emitting fake progress', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const state = {}
  abortableFetch(t, state)
  let snapshots = 0
  const pending = streamAgentEvents(options({ idleTimeoutMs: 1000, handlers: { onSnapshot: () => { snapshots++ } } }))
  const rejected = assert.rejects(pending, /连接超时/)
  await flush()
  t.mock.timers.tick(900)
  state.controller.enqueue(bytes(': keep-alive\n\n'))
  await flush()
  t.mock.timers.tick(900)
  await flush()
  assert.equal(state.signal.aborted, false)
  assert.equal(snapshots, 0)
  t.mock.timers.tick(100)
  await rejected
})

test('page cancellation aborts the actual fetch/reader', async t => {
  const state = {}, controller = new AbortController()
  abortableFetch(t, state)
  const pending = streamAgentEvents(options({ signal: controller.signal }))
  const rejected = assert.rejects(pending, error => error.name === 'AbortError')
  await flush()
  controller.abort()
  await rejected
  assert.equal(state.signal.aborted, true)
})

test('a done event closes the response reader rather than leaving an open connection', async t => {
  let cancelled = false
  t.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(bytes('event: done\ndata: {}\n\n')) },
    cancel() { cancelled = true },
  })))
  await streamAgentEvents(options())
  assert.equal(cancelled, true)
})
