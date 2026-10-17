import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'
import { pptPublicationState } from '../src/utils/lessonPublication.ts'

function run() {
  return { output_data: {
    artifact_bundle: { ppt: { pipeline_version: 'ppt-master-svg-v2', revision_id: 'r1' } },
    artifacts: { ppt: { revision_id: 'r1', attempt_id: 'ok' } },
    artifact_attempt: { id: 'ok', status: 'completed', requested_types: ['ppt'] },
  } }
}

test('publication binds the current immutable revision', () => {
  assert.deepEqual(pptPublicationState(run()), { revision: 'r1', valid: true, previous: false })
  const value = run()
  value.output_data.artifacts.ppt.revision_id = 'stale'
  assert.equal(pptPublicationState(value).valid, false)
})
test('legacy decks remain publishable without modern revision metadata', () => {
  assert.equal(pptPublicationState(null).valid, false)
  const value = run()
  delete value.output_data.artifact_bundle.ppt.pipeline_version
  delete value.output_data.artifact_bundle.ppt.revision_id
  delete value.output_data.artifacts.ppt.revision_id
  assert.deepEqual(pptPublicationState(value), { revision: '', valid: true, previous: false })
  value.output_data.artifact_bundle.ppt.pipeline_version = 'ppt-master-svg-v2'
  assert.equal(pptPublicationState(value).valid, false)
})
test('failed/partial retries require an extra acknowledgement', () => {
  for (const status of ['failed', 'partial', 'running', 'queued']) {
    const value = run()
    Object.assign(value.output_data.artifact_attempt, { id: 'new', status })
    assert.equal(pptPublicationState(value).previous, true)
  }
})
test('server per-artifact state survives later document attempts and explicit restore clears it', () => {
  const value = run()
  value.output_data.artifact_attempt.requested_types = ['lesson_plan']
  value.output_data.artifacts.ppt.requires_previous_confirmation = true
  assert.equal(pptPublicationState(value).previous, true)
  value.output_data.artifacts.ppt.requires_previous_confirmation = false
  assert.equal(pptPublicationState(value).previous, false)
})
test('publication UI wires version binding, resets acknowledgements and warns about previous decks', async () => {
  const source = await readFile(new URL('../src/views/LessonPrepWorkspaceView.vue', import.meta.url), 'utf8')
  assert.match(source, /expected_ppt_revision: publishPpt\.value \? publicationPpt\.value\.revision/)
  assert.match(source, /allow_previous_ppt:/)
  assert.match(source, /v-model="previousPptConfirmed"/)
  assert.match(source, /previousPptConfirmed\.value = false/)
  assert.match(source, /publicationConfirmed\.value = false/)
  assert.match(source, /const payload = \{[\s\S]+await ElMessageBox\.confirm/)
})

async function publicationUi() {
  const source = await readFile(new URL('../src/views/LessonPrepWorkspaceView.vue', import.meta.url), 'utf8')
  const calls = [], messages = []
  const ref = value => ({ value })
  const current = { ...run(), id: 1, status: 'completed', current_step: 3 }
  const env = {
    currentRun: ref(current), acting: ref(false), isExecuting: ref(false), isBrowsingHistory: ref(false),
    selectedTeachingClassId: ref(7), publicationConfirmed: ref(true), previousPptConfirmed: ref(false),
    publicationPpt: ref(pptPublicationState(current)), publishPpt: ref(true), publishDiscussions: ref(false),
    classroomActivities: ref([]), selectedDiscussionIndices: ref([]), publishTitle: ref('公开课成果'),
    publishDescription: ref('测试'), publishedResult: ref(null),
    ElMessage: Object.fromEntries(['warning', 'success', 'error'].map(key => [key, text => messages.push([key, text])])),
    ElMessageBox: { confirm: async () => true },
    agentApi: { publish: async (...args) => { calls.push(args); return { data: { data: { id: 8 } } } } },
    versionFailure: (error, fallback) => error.response?.data?.detail || fallback,
    computed: fn => ({ get value() { return fn() } }),
  }
  const computedSource = source.slice(source.indexOf('const canPublish ='), source.indexOf('const maxAvailableStage ='))
  env.canPublish = new Function(...Object.keys(env), `${computedSource}; return canPublish`)(...Object.values(env))
  const handlerSource = source.slice(source.indexOf('async function publishLesson()'), source.indexOf('function chooseTemplateFile('))
  const compiled = ts.transpileModule(handlerSource, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const publish = new Function(...Object.keys(env), `${compiled}; return publishLesson`)(...Object.values(env))
  return { env, publish, calls, messages }
}

test('actual publish handler sends the reviewed revision and an explicit snapshot', async () => {
  const ui = await publicationUi()
  await ui.publish()
  assert.equal(ui.calls.length, 1)
  assert.equal(ui.calls[0][0], 1)
  assert.equal(ui.calls[0][1].expected_ppt_revision, 'r1')
  assert.equal(ui.calls[0][1].allow_previous_ppt, false)
  assert.equal(ui.env.publishedResult.value.id, 8)
  assert.equal(ui.env.acting.value, false)
})
test('actual publication guard blocks previous PPTs until separately acknowledged', async () => {
  const ui = await publicationUi()
  ui.env.publicationPpt.value.previous = true
  await ui.publish()
  assert.equal(ui.calls.length, 0)
  ui.env.previousPptConfirmed.value = true
  await ui.publish()
  assert.equal(ui.calls[0][1].allow_previous_ppt, true)
})
test('changing reviewed content while the final dialog is open cannot publish a different selection', async () => {
  const ui = await publicationUi()
  let confirm
  ui.env.ElMessageBox.confirm = () => new Promise(resolve => { confirm = resolve })
  const pending = ui.publish()
  ui.env.publicationPpt.value.revision = 'r2'
  // The synchronous selection watch clears the acknowledgement.
  ui.env.publicationConfirmed.value = false
  confirm()
  await pending
  assert.equal(ui.calls.length, 0)
  assert.match(ui.messages.at(-1)[1], /变化/)
})
test('cancelling publication does not submit or raise an unhandled rejection', async () => {
  const ui = await publicationUi()
  ui.env.ElMessageBox.confirm = async () => { throw 'cancel' }
  await ui.publish()
  assert.equal(ui.calls.length, 0)
  assert.equal(ui.env.publishedResult.value, null)
})
test('server publication conflicts are visible and require a fresh acknowledgement', async () => {
  const ui = await publicationUi()
  ui.env.agentApi.publish = async () => { throw { response: { data: { detail: '课件版本已变化' } } } }
  await ui.publish()
  assert.equal(ui.env.publicationConfirmed.value, false)
  assert.equal(ui.env.previousPptConfirmed.value, false)
  assert.equal(ui.env.acting.value, false)
  assert.deepEqual(ui.messages.at(-1), ['error', '课件版本已变化'])
})
