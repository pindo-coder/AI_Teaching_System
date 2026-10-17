import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { ref, watch, nextTick } from 'vue'
import ts from 'typescript'
import { createAgentRunMonitor } from '../src/utils/agentRunMonitor.ts'
import { lessonArtifactProgress } from '../src/utils/lessonArtifactProgress.ts'

const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve() }
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function run(status = 'running', done = 0, id = 1) {
  return { id, status, current_step: 3, evidence_snapshot: [], input_data: { artifact_output_types: ['ppt'] },
    output_data: { artifact_attempt: { status: status === 'running' ? 'running' : 'completed', requested_types: ['ppt'] } },
    steps: [{ step_key: 'generate_artifacts', status, output_data: {
      ppt_workflow: { stage: done ? 'designing' : 'planning', completed_pages: done, total_pages: 10 },
    } }],
  }
}
function fixture(t, extra = {}) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const state = { server: run(), snapshots: [], requests: [], streams: [], errors: [] }
  const monitor = createAgentRunMonitor({
    fetchRun: async (id, signal) => { state.requests.push({ id, signal }); return structuredClone(state.server) },
    stream: (id, handlers, signal) => {
      const pending = deferred()
      state.streams.push({ id, handlers, signal, ...pending })
      signal.addEventListener('abort', () => pending.reject(new DOMException('cancelled', 'AbortError')), { once: true })
      return pending.promise
    },
    onSnapshot: value => state.snapshots.push(value),
    onError: (error, fatal) => state.errors.push({ error, fatal }),
    ...extra,
  })
  t.after(() => monitor.stop())
  return { ...state, state, monitor, async tick(ms) { t.mock.timers.tick(ms); await flush() } }
}

test('a silent/buffered SSE still updates the real percentage without refreshing the page', async t => {
  const f = fixture(t)
  f.monitor.start(1)
  await flush()
  const before = lessonArtifactProgress(f.snapshots.at(-1)).percentage
  f.state.server = run('running', 6)
  await f.tick(5000)
  const after = lessonArtifactProgress(f.snapshots.at(-1)).percentage
  assert.ok(after > before)
  assert.equal(f.snapshots.at(-1).steps[0].output_data.ppt_workflow.completed_pages, 6)
  assert.equal(f.streams.length, 1)
})

test('no backend change does not fabricate progress, even after several polls', async t => {
  const f = fixture(t)
  f.monitor.start(1)
  await flush()
  const before = lessonArtifactProgress(f.snapshots.at(-1)).percentage
  for (let i = 0; i < 4; i++) await f.tick(5000)
  assert.equal(lessonArtifactProgress(f.snapshots.at(-1)).percentage, before)
})

for (const ending of ['EOF', 'error']) {
  test(`stream ${ending} triggers read-only refresh and reconnection, not a task retry`, async t => {
    const f = fixture(t)
    f.monitor.start(1)
    await flush()
    f.state.server = run('running', 4)
    if (ending === 'EOF') f.streams[0].resolve()
    else f.streams[0].reject(new Error('proxy timeout'))
    await flush()
    assert.equal(f.snapshots.at(-1).steps[0].output_data.ppt_workflow.completed_pages, 4)
    await f.tick(1000)
    assert.equal(f.streams.length, 2)
    assert.equal(f.errors.length, 0)
  })
}

test('a delayed SSE snapshot cannot overwrite newer HTTP progress or completion', async t => {
  const f = fixture(t)
  f.monitor.start(1)
  await flush()
  f.state.server = run('running', 8)
  await f.tick(5000)
  f.streams[0].handlers.onSnapshot(run('running', 1))
  await flush()
  assert.equal(f.snapshots.at(-1).steps[0].output_data.ppt_workflow.completed_pages, 8)
  f.state.server = run('completed', 10)
  f.streams[0].handlers.onDone()
  await flush()
  const requests = f.requests.length
  assert.equal(f.snapshots.at(-1).status, 'completed')
  assert.equal(f.streams[0].signal.aborted, true)
  f.streams[0].handlers.onSnapshot(run())
  await f.tick(60_000)
  assert.equal(f.requests.length, requests)
  assert.equal(f.snapshots.at(-1).status, 'completed')
})

for (const status of ['completed', 'failed', 'cancelled', 'waiting_confirmation']) {
  test(`HTTP ${status} stops all polling/reconnection even without a done event`, async t => {
    const f = fixture(t)
    f.monitor.start(1)
    await flush()
    f.state.server = run(status, 10)
    await f.tick(5000)
    const requests = f.requests.length
    assert.equal(f.snapshots.at(-1).status, status)
    assert.equal(f.streams[0].signal.aborted, true)
    await f.tick(60_000)
    assert.equal(f.requests.length, requests)
  })
}

test('duplicate subscriptions do not open duplicate streams or poll loops', async t => {
  const f = fixture(t)
  f.monitor.start(1)
  f.monitor.start(1)
  f.monitor.start(1)
  await flush()
  assert.equal(f.requests.length, 1)
  assert.equal(f.streams.length, 1)
  await f.tick(5000)
  assert.equal(f.requests.length, 2)
})

test('slow GETs are serialized and a burst of stream events coalesces to one follow-up', async t => {
  const pending = deferred()
  let calls = 0
  const f = fixture(t, { fetchRun: async () => { calls++; return calls === 1 ? pending.promise : run('running', 3) } })
  f.monitor.start(1)
  for (let i = 0; i < 8; i++) f.streams[0].handlers.onSnapshot(run())
  await f.tick(30_000)
  assert.equal(calls, 1)
  pending.resolve(run('running', 1))
  await flush()
  assert.equal(calls, 2)
  assert.equal(f.snapshots.at(-1).steps[0].output_data.ppt_workflow.completed_pages, 3)
})

test('switching tasks aborts old requests and ignores late old-task successes', async t => {
  const pending = deferred(), signals = []
  const f = fixture(t, { fetchRun: async (id, signal) => { signals.push(signal); return id === 1 ? pending.promise : run('running', 2, id) } })
  f.monitor.start(1)
  f.monitor.start(2)
  await flush()
  assert.equal(signals[0].aborted, true)
  assert.equal(f.streams[0].signal.aborted, true)
  pending.resolve(run('completed', 10, 1))
  await flush()
  f.streams[0].handlers.onDone()
  assert.ok(f.snapshots.every(value => value.id === 2))
})

test('leaving the page stops pending work and ignores late failures', async t => {
  const pending = deferred()
  const f = fixture(t, { fetchRun: () => pending.promise })
  f.monitor.start(1)
  f.monitor.stop()
  pending.reject(new Error('late network failure'))
  await flush()
  await f.tick(60_000)
  assert.equal(f.snapshots.length, 0)
  assert.equal(f.errors.length, 0)
  assert.equal(f.streams.length, 1)
})

test('temporary HTTP failures back off, retain the last state, and recover', async t => {
  let fail = true, calls = 0
  const f = fixture(t, { fetchRun: async () => { calls++; if (fail) throw new Error('offline'); return run('running', 7) } })
  f.monitor.start(1)
  await flush()
  assert.equal(f.errors[0].fatal, false)
  await f.tick(5000)
  assert.equal(calls, 1)
  fail = false
  await f.tick(5000)
  assert.equal(calls, 2)
  assert.equal(f.snapshots.at(-1).steps[0].output_data.ppt_workflow.completed_pages, 7)
})

for (const status of [401, 403, 404]) {
  test(`HTTP ${status} stops automatic requests instead of reconnecting forever`, async t => {
    let calls = 0
    const f = fixture(t, { fetchRun: async () => { calls++; throw { response: { status } } } })
    f.monitor.start(1)
    await flush()
    assert.equal(f.errors[0].fatal, true)
    await f.tick(60_000)
    assert.equal(calls, 1)
    assert.equal(f.streams[0].signal.aborted, true)
  })
}

test('foreground/network recovery can request an immediate refresh without duplicate streams', async t => {
  const f = fixture(t)
  f.monitor.start(1)
  await flush()
  f.state.server = run('running', 7)
  f.monitor.refresh()
  await flush()
  assert.equal(f.snapshots.at(-1).steps[0].output_data.ppt_workflow.completed_pages, 7)
  assert.equal(f.streams.length, 1)
})

test('a later generation attempt on the same run can start a fresh monitor', async t => {
  const f = fixture(t)
  f.state.server = run('completed', 10)
  f.monitor.start(1)
  await flush()
  f.state.server = run('running', 0)
  f.monitor.start(1)
  await flush()
  assert.equal(f.snapshots.at(-1).status, 'running')
  assert.equal(f.streams.length, 2)
})

test('the actual page wires lifecycle, foreground refresh and cancellable read-only monitoring', async () => {
  const source = await readFile(new URL('../src/views/LessonPrepWorkspaceView.vue', import.meta.url), 'utf8')
  assert.match(source, /createAgentRunMonitor<AgentRun>/)
  assert.match(source, /agentApi\.detail\(id, signal\)/)
  assert.match(source, /agentApi\.stream\(id, handlers, signal\)/)
  assert.match(source, /currentRun\.value\?\.id !== run\.id/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{\s*progressMonitor\.stop\(\)/)
  assert.match(source, /visibilitychange.*refreshVisibleProgress/)
  assert.match(source, /online.*refreshVisibleProgress/)
  assert.match(source, /v-if="progressSyncWarning"/)
})

test('actual page monitor and synchronous Vue watch update progress and stop on completion without reload', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const source = await readFile(new URL('../src/views/LessonPrepWorkspaceView.vue', import.meta.url), 'utf8')
  const controller = source.slice(source.indexOf('const progressMonitor ='), source.indexOf('async function startAgent()'))
  const watchStart = source.indexOf('watch(() => [currentRun.value?.id, currentRun.value?.status]')
  const lifecycle = source.slice(watchStart, source.indexOf('onMounted(() => {', watchStart))
    .replace('watch(() =>', 'const disposeWatch = watch(() =>')
  let server = run(), requests = 0
  const signals = []
  const currentRun = ref(null), activeStage = ref(1), warning = ref('')
  const compiled = ts.transpileModule(controller + lifecycle, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  const env = {
    currentRun, activeStage, progressSyncWarning: warning, createAgentRunMonitor, watch,
    syncArtifactInput() {}, document: { hidden: false },
    agentApi: {
      detail: async () => { requests++; return { data: { data: structuredClone(server) } } },
      stream: (_id, _handlers, signal) => {
        signals.push(signal)
        return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }))
      },
    },
  }
  const ui = new Function(...Object.keys(env), `${compiled}; return { progressMonitor, disposeWatch, syncRunStage }`)(...Object.values(env))
  t.after(() => { ui.disposeWatch(); ui.progressMonitor.stop() })
  // Mirrors applyRun()/the queued generation response assigning currentRun.
  currentRun.value = structuredClone(server)
  ui.syncRunStage(currentRun.value)
  await flush(); await nextTick()
  assert.equal(activeStage.value, 4)
  const before = lessonArtifactProgress(currentRun.value).percentage
  server = run('running', 7)
  activeStage.value = 5 // inspecting the retained previous PPT while generating
  t.mock.timers.tick(5000)
  await flush(); await nextTick()
  assert.ok(lessonArtifactProgress(currentRun.value).percentage > before)
  assert.equal(activeStage.value, 5) // polling must not repeatedly force stage 4
  server = run('completed', 10)
  server.output_data.artifacts = { ppt: { file_name: '测试.pptx' } }
  t.mock.timers.tick(5000)
  await flush(); await nextTick()
  assert.equal(currentRun.value.status, 'completed')
  assert.equal(activeStage.value, 5)
  assert.equal(lessonArtifactProgress(currentRun.value).percentage, 100)
  assert.equal(signals[0].aborted, true)
  const stoppedAt = requests
  t.mock.timers.tick(60_000)
  await flush()
  assert.equal(requests, stoppedAt)
})
