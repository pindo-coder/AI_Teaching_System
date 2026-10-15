import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import { pathToFileURL } from 'node:url'
import * as Vue from 'vue'
import ts from 'typescript'
import { workspaceAiRequestError, WORKSPACE_AI_REQUEST_EVENT } from '../src/utils/workspaceAiEvents.ts'
import { createWorkspaceContextLoader } from '../src/utils/workspaceAiContext.ts'

const require = createRequire(import.meta.url)
const vueUrl = pathToFileURL(require.resolve('vue')).href
const { parse, compileScript } = createRequire(require.resolve('vue'))('@vue/compiler-sfc')
const toModule = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const moduleUrl = (relative) => new URL(relative, import.meta.url).href
const flush = async () => { for (let index = 0; index < 15; index += 1) await Vue.nextTick() }
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const request = (learningStage = 'exam', extra = {}) => ({
  courseId: 1, chapterId: 17, learningStage, taskType: 'question_answer',
  mode: 'agent', autoSend: true, prompt: '请制定学习计划。', ...extra,
})
const contextFor = (scope) => ({
  ...scope, chapter_ids: scope.chapter_ids || (scope.chapter_id ? [scope.chapter_id] : []),
  course_name: '测试教材', chapter_title: '测试专题', source: 'page', confidence: 'high',
  chapters: [], candidates: [], state_summary: [], chapter_titles: [], requires_chapter_selection: false,
})

for (const stage of ['preview', 'review', 'exam']) {
  test(`home accepts ${stage} without an explicit route stage`, () => {
    assert.equal(workspaceAiRequestError(request(stage), {}), null)
  })
}
test('explicit learning page still rejects a mismatched scope', () => {
  assert.ok(workspaceAiRequestError(request(), { learningStage: 'preview' }))
  assert.ok(workspaceAiRequestError(request(), { courseId: 2 }))
  assert.ok(workspaceAiRequestError(request(), { chapterId: 18 }))
  assert.equal(workspaceAiRequestError(request(), { courseId: 1, chapterId: 17, learningStage: 'exam' }), null)
})
test('invalid requests are rejected before lookup or model handoff', () => {
  for (const value of [null, {}, request('invalid'), request('exam', { courseId: 0 }),
    request('exam', { chapterId: 1.5 }), request('exam', { prompt: ' ' })]) {
    assert.ok(workspaceAiRequestError(value, {}))
  }
})
test('identical pending context lookups share their promise', async () => {
  const pending = deferred()
  let calls = 0
  const loading = [], contexts = []
  const loader = createWorkspaceContextLoader({
    fetch: () => { calls += 1; return pending.promise },
    onContext: (value) => contexts.push(value), onLoading: (value) => loading.push(value),
  })
  const first = loader.load({ stage: 'exam' })
  assert.equal(first, loader.load({ stage: 'exam' }))
  pending.resolve('exam-context')
  assert.equal(await first, 'exam-context')
  assert.equal(calls, 1)
  assert.deepEqual(loading, [true, false])
  assert.deepEqual(contexts, ['exam-context'])
})
for (const staleFails of [false, true]) {
  test(`a late ${staleFails ? 'failure' : 'success'} cannot replace the newest context`, async () => {
    const old = deferred(), latest = deferred(), contexts = [], loading = []
    const loader = createWorkspaceContextLoader({
      fetch: ({ stage }) => stage === 'preview' ? old.promise : latest.promise,
      onContext: (value) => contexts.push(value), onLoading: (value) => loading.push(value),
    })
    const first = loader.load({ stage: 'preview' })
    const second = loader.load({ stage: 'exam' })
    latest.resolve('exam-context')
    assert.equal(await second, 'exam-context')
    if (staleFails) old.reject(new Error('stale lookup failed'))
    else old.resolve('preview-context')
    assert.equal(await first, null)
    assert.deepEqual(contexts, ['exam-context'])
    assert.deepEqual(loading, [true, true, false])
  })
}
test('reset invalidates a pending context lookup', async () => {
  const pending = deferred(), contexts = []
  const loader = createWorkspaceContextLoader({
    fetch: () => pending.promise, onContext: (value) => contexts.push(value), onLoading() {},
  })
  const result = loader.load({})
  loader.reset()
  pending.resolve('old-page-context')
  assert.equal(await result, null)
  assert.deepEqual(contexts, [null])
})

// Run the real AgentDock setup, template, Vue lifecycle and event listener in a
// DOM-free renderer. Only the API boundary and assistant presentation are test
// doubles: no fabricated model answer is used or claimed as a DeepSeek test.
const renderer = Vue.createRenderer({
  createElement: (type) => ({ type, children: [], props: {}, parent: null }),
  createText: (text) => ({ type: 'text', text, parent: null }),
  createComment: (text) => ({ type: 'comment', text, parent: null }),
  setText: (node, text) => { node.text = text },
  setElementText: (node, text) => { node.text = text; node.children = [] },
  parentNode: (node) => node.parent,
  nextSibling: (node) => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  patchProp: (node, key, _old, value) => { node.props[key] = value },
  insert: (node, parent, anchor = null) => {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(node)
    else parent.children.splice(index, 0, node)
    node.parent = parent
  },
  remove: (node) => {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    node.parent = null
  },
})
function allNodes(node) { return [node, ...(node.children || []).flatMap(allNodes)] }
let fixtureNumber = 0
async function mountDock({ fetch, route, workspace } = {}) {
  const fixtureKey = `agentDockFixture${++fixtureNumber}`
  const fixture = {
    auth: Vue.reactive({ isAuthenticated: true }),
    route: Vue.reactive({ name: 'dashboard', fullPath: '/', params: {}, query: {}, ...route }),
    workspace: Vue.reactive({ currentCourse: { id: 1 }, currentChapter: { id: 17 }, currentClass: null, ...workspace }),
    busy: Vue.ref(false), contexts: [], handoffs: [], notices: [],
  }
  fixture.aiApi = { workspaceContext: async (scope) => {
    fixture.contexts.push(scope)
    const resolved = fetch ? await fetch(scope) : contextFor(scope)
    return { data: { data: resolved } }
  } }
  globalThis[fixtureKey] = fixture
  const previousWindow = globalThis.window
  globalThis.window = new EventTarget()
  const fixtureReference = `globalThis[${JSON.stringify(fixtureKey)}]`
  const imports = {
    vue: toModule(`export * from ${JSON.stringify(vueUrl)};
      export const Transition = {props:['name'],setup(_, {slots}) {return () => slots.default?.()}};`),
    'vue-router': toModule(`export const useRoute = () => ${fixtureReference}.route;`),
    'element-plus': toModule(`export const ElMessage = Object.fromEntries(['info','warning','error'].map(kind =>
      [kind, message => ${fixtureReference}.notices.push({kind,message})]));`),
    '@element-plus/icons-vue': toModule('const Icon = {render: () => null}; export const ArrowDown = Icon, Check = Icon, MagicStick = Icon, RefreshRight = Icon, Setting = Icon;'),
    '@/api/ai': toModule(`export const aiApi = ${fixtureReference}.aiApi;`),
    '@/stores/auth': toModule(`export const useAuthStore = () => ${fixtureReference}.auth;`),
    '@/stores/workspace': toModule(`export const useWorkspaceStore = () => ${fixtureReference}.workspace;`),
    '@/utils/workspaceAiEvents': moduleUrl('../src/utils/workspaceAiEvents.ts'),
    '@/utils/workspaceAiContext': moduleUrl('../src/utils/workspaceAiContext.ts'),
    './WorkspaceAiAssistant.vue': toModule(`import {h,computed} from ${JSON.stringify(vueUrl)};
      export default {props:['context','learningStage','courseId','chapterId','teachingClassId','pageName'],
        setup(props,{expose}) {
          expose({isBusy:computed(() => ${fixtureReference}.busy.value),
            async applyExternalRequest(request) {
              ${fixtureReference}.handoffs.push({request, context:props.context, stage:props.learningStage});
            }});
          return () => h('assistant-test');
        }};`),
  }
  const source = await readFile(new URL('../src/components/AgentDock.vue', import.meta.url), 'utf8')
  const compiled = compileScript(parse(source).descriptor, { id: 'agent-dock-test', inlineTemplate: true })
  let code = ts.transpileModule(compiled.content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  code = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, name) => {
    assert.ok(imports[name], `Unexpected component dependency: ${name}`)
    return `from ${JSON.stringify(imports[name])}`
  })
  const component = (await import(toModule(code))).default
  const root = { type: 'root', children: [] }
  const app = renderer.createApp(component)
  app.component('el-icon', { setup: (_, { slots }) => () => Vue.h('span', slots.default?.()) })
  app.component('el-button', { setup: (_, { slots }) => () => Vue.h('button', slots.default?.()) })
  app.component('el-popover', { setup: (_, { slots }) => () => Vue.h('div', [slots.reference?.(), slots.default?.()]) })
  app.mount(root)
  await flush()
  return {
    ...fixture, root,
    dispatch(value) { window.dispatchEvent(new CustomEvent(WORKSPACE_AI_REQUEST_EVENT, { detail: value })) },
    async close() { app.unmount(); await flush(); globalThis.window = previousWindow; delete globalThis[fixtureKey] },
  }
}

for (const stage of ['preview', 'review', 'exam']) {
  test(`real Dock opens and hands off a home ${stage} plan exactly once`, async () => {
    const dock = await mountDock()
    try {
      dock.dispatch(request(stage))
      await flush()
      assert.equal(dock.handoffs.length, 1)
      assert.equal(dock.handoffs[0].stage, stage)
      assert.equal(dock.handoffs[0].context.learning_stage, stage)
      assert.equal(dock.handoffs[0].request.autoSend, true)
      assert.equal(dock.notices.length, 0)
      assert.ok(allNodes(dock.root).some((node) => node.type === 'assistant-test'))
    } finally { await dock.close() }
  })
}
test('home Chat opens without auto-send, even when cached workspace differs', async () => {
  const dock = await mountDock({ workspace: { currentCourse: { id: 99 }, currentChapter: { id: 88 } } })
  try {
    dock.dispatch(request('review', { mode: 'chat', autoSend: false }))
    await flush()
    assert.equal(dock.handoffs.length, 1)
    assert.equal(dock.handoffs[0].request.mode, 'chat')
    assert.equal(dock.handoffs[0].request.autoSend, false)
    assert.equal(dock.handoffs[0].context.course_id, 1)
    assert.equal(dock.handoffs[0].context.chapter_id, 17)
  } finally { await dock.close() }
})
test('home request is not lost while the initial context is loading', async () => {
  const initial = deferred()
  const dock = await mountDock({ fetch: (scope) => scope.chapter_ids ? contextFor(scope) : initial.promise })
  try {
    dock.dispatch(request())
    await flush()
    assert.equal(dock.handoffs.length, 1)
    initial.resolve(contextFor({ course_id: 1, chapter_id: 17, learning_stage: 'preview' }))
    await flush()
    assert.equal(dock.handoffs[0].context.learning_stage, 'exam')
    assert.ok(allNodes(dock.root).some((node) => node.text?.includes('考前冲刺')))
  } finally { await dock.close() }
})
test('duplicate clicks during opening only hand off once', async () => {
  const pending = deferred()
  const dock = await mountDock({ fetch: (scope) => scope.chapter_ids ? pending.promise : contextFor(scope) })
  try {
    dock.dispatch(request())
    dock.dispatch(request())
    await flush()
    assert.ok(allNodes(dock.root).some((node) => node.props?.role === 'status'))
    pending.resolve(contextFor({ course_id: 1, chapter_id: 17, chapter_ids: [17], learning_stage: 'exam' }))
    await flush()
    assert.equal(dock.handoffs.length, 1)
    assert.ok(dock.notices.some((notice) => notice.kind === 'info'))
  } finally { await dock.close() }
})
test('failed or mismatched context shows an error instead of sending with stale scope', async () => {
  for (const mismatched of [false, true]) {
    const dock = await mountDock({ fetch: (scope) => {
      if (!scope.chapter_ids) return contextFor(scope)
      if (mismatched) return contextFor({ ...scope, chapter_id: 88 })
      throw new Error('context service unavailable')
    } })
    try {
      dock.dispatch(request())
      await flush()
      assert.equal(dock.handoffs.length, 0)
      assert.ok(allNodes(dock.root).some((node) => node.props?.role === 'alert'))
      assert.ok(dock.notices.some((notice) => notice.kind === 'error'))
    } finally { await dock.close() }
  }
})
test('a learning page warns about a wrong stage instead of silently ignoring it', async () => {
  const dock = await mountDock({ route: { fullPath: '/courses/1/chapters/17/preview', params: { courseId: '1', chapterId: '17', stage: 'preview' } } })
  try {
    dock.dispatch(request('exam'))
    await flush()
    assert.equal(dock.handoffs.length, 0)
    assert.ok(dock.notices.some((notice) => notice.kind === 'warning'))
  } finally { await dock.close() }
})
test('a matching learning-page request still opens normally', async () => {
  const dock = await mountDock({ route: { fullPath: '/courses/1/chapters/17/review', params: { courseId: '1', chapterId: '17', stage: 'review' } } })
  try {
    dock.dispatch(request('review', { mode: 'chat', autoSend: false }))
    await flush()
    assert.equal(dock.handoffs.length, 1)
    assert.equal(dock.handoffs[0].stage, 'review')
    assert.equal(dock.notices.length, 0)
  } finally { await dock.close() }
})
test('an opening failure can be retried from the same home entry', async () => {
  let failed = true
  const dock = await mountDock({ fetch: (scope) => {
    if (scope.chapter_ids && failed) throw new Error('temporary lookup failure')
    return contextFor(scope)
  } })
  try {
    dock.dispatch(request())
    await flush()
    assert.equal(dock.handoffs.length, 0)
    failed = false
    dock.dispatch(request())
    await flush()
    assert.equal(dock.handoffs.length, 1)
    assert.ok(!allNodes(dock.root).some((node) => node.props?.role === 'alert'))
  } finally { await dock.close() }
})
test('navigation cancels pending opening and clears the manual stage', async () => {
  const pending = deferred()
  const dock = await mountDock({ fetch: (scope) => scope.chapter_ids ? pending.promise : contextFor(scope) })
  try {
    dock.dispatch(request())
    await flush()
    dock.route.fullPath = '/courses'
    dock.route.name = 'courses'
    await flush()
    pending.resolve(contextFor({ course_id: 1, chapter_id: 17, chapter_ids: [17], learning_stage: 'exam' }))
    await flush()
    assert.equal(dock.handoffs.length, 0)
    assert.equal(dock.notices.length, 0)
    assert.ok(allNodes(dock.root).some((node) => node.text?.includes('课前预习')))
  } finally { await dock.close() }
})
test('an already running assistant is not unmounted or overwritten by a new entry click', async () => {
  const dock = await mountDock()
  try {
    dock.dispatch(request('preview', { mode: 'chat', autoSend: false }))
    await flush()
    dock.busy.value = true
    dock.dispatch(request('exam'))
    await flush()
    assert.equal(dock.handoffs.length, 1)
    assert.ok(dock.notices.some((notice) => notice.kind === 'info'))
    assert.ok(allNodes(dock.root).some((node) => node.type === 'assistant-test'))
  } finally { await dock.close() }
})
