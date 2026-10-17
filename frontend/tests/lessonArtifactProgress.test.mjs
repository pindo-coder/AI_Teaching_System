import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { lessonArtifactProgress } from '../src/utils/lessonArtifactProgress.ts'

function run(stage = 'designing', done = 3, total = 10) {
  return {
    id: 1, status: 'running', current_step: 3, updated_time: '2026-10-17T00:05:00Z', finished_time: null,
    input_data: { artifact_output_types: ['ppt'], ppt_preferences: { include_visuals: true } },
    output_data: { artifact_attempt: { id: 'new-attempt', status: 'running', requested_types: ['ppt'], started_time: '2026-10-17T00:00:00Z' } },
    steps: [{ step_key: 'generate_artifacts', status: 'running', output_data: {
      ppt_workflow: { stage, completed_pages: done, total_pages: total },
    }, started_time: '2026-10-17T00:00:00Z', finished_time: null }],
  }
}

test('no task or an unstarted pending step has no fabricated progress', () => {
  assert.equal(lessonArtifactProgress(null), null)
  const value = run()
  delete value.output_data.artifact_attempt
  value.steps[0].status = 'pending'
  assert.equal(lessonArtifactProgress(value), null)
})

test('submitting a new attempt clears the old 100 percent immediately', () => {
  const value = run('completed', 10)
  value.status = value.output_data.artifact_attempt.status = value.steps[0].status = 'completed'
  assert.equal(lessonArtifactProgress(value).percentage, 100)
  const submitting = lessonArtifactProgress(value, { submitting: true })
  assert.equal(submitting.percentage, 0)
  assert.equal(submitting.status, undefined)
  assert.match(submitting.label, /提交/)
})

test('queued requests show zero rather than an old success or a looping fixed value', () => {
  const value = run()
  value.status = value.output_data.artifact_attempt.status = value.steps[0].status = 'queued'
  const progress = lessonArtifactProgress(value)
  assert.equal(progress.percentage, 0)
  assert.equal(progress.status, undefined)
})

test('actual page checkpoints increase percentage and show completed and remaining pages', () => {
  const percentages = [0, 3, 5, 10].map(done => lessonArtifactProgress(run('designing', done)).percentage)
  assert.ok(percentages.every((value, index) => !index || value > percentages[index - 1]))
  assert.ok(percentages.at(-1) < 100)
  assert.match(lessonArtifactProgress(run()).detail, /已设计 3\/10 页，剩余 7 页/)
})

test('time passing does not invent completed work or advance percentage', () => {
  const value = run()
  const earlier = lessonArtifactProgress(value, { now: Date.parse('2026-10-17T00:01:00Z') })
  const later = lessonArtifactProgress(value, { now: Date.parse('2026-10-17T00:02:03Z') })
  assert.equal(earlier.percentage, later.percentage)
  assert.equal(later.elapsed, '已用时 2 分 3 秒')
})

test('illustration and export are distinct phases and never claim file readiness', () => {
  const designed = lessonArtifactProgress(run('designing', 10))
  const images = lessonArtifactProgress(run('illustrating', 0))
  const exporting = lessonArtifactProgress(run('exporting', 10))
  const saving = lessonArtifactProgress(run('completed', 10))
  assert.ok(designed.percentage < images.percentage)
  assert.ok(images.percentage < exporting.percentage)
  assert.ok(exporting.percentage < saving.percentage)
  assert.ok(saving.percentage < 100)
  assert.doesNotMatch(images.detail, /0\/10/)
  assert.match(exporting.label, /导出/)
})

test('an image-only resume shows reused pages, paid images and remaining image work', () => {
  const value = run('illustrating', 0)
  value.steps[0].output_data.ppt_workflow.resume = {
    requested: true, resumed: true, reused_pages: 10, reused_images: 1, generated_images: 0, pending_images: 2,
  }
  const progress = lessonArtifactProgress(value)
  assert.equal(progress.label, '正在补全缺失插图')
  assert.match(progress.detail, /已复用 10 页设计、1 张已有插图/)
  assert.match(progress.detail, /已补 0\/2 张/)
  assert.ok(progress.percentage < 100)
  value.steps[0].output_data.ppt_workflow.resume.generated_images = 1
  value.steps[0].output_data.ppt_workflow.resume.pending_images = 1
  assert.match(lessonArtifactProgress(value).detail, /已补 1\/2 张/)
})

test('an export retry with all paid images cached does not claim it is generating new ones', () => {
  const value = run('illustrating', 0)
  value.steps[0].output_data.ppt_workflow.resume = {
    resumed: true, reused_pages: 10, reused_images: 2, generated_images: 0, pending_images: 0,
  }
  const progress = lessonArtifactProgress(value)
  assert.equal(progress.label, '插图已齐全，准备导出')
  assert.match(progress.detail, /无需重新调用成图模型/)
  delete value.steps[0].output_data.ppt_workflow.resume.pending_images
  assert.doesNotMatch(lessonArtifactProgress(value).detail, /无需重新调用/) // legacy server fallback
})

test('waiting for extra documents does not mark the whole request complete', () => {
  const value = run('completed', 10)
  value.output_data.artifact_attempt.requested_types.push('lesson_plan', 'classroom_activities')
  const progress = lessonArtifactProgress(value)
  assert.ok(progress.percentage < lessonArtifactProgress(run('completed', 10)).percentage)
  assert.match(progress.label, /教案与课堂活动/)
  assert.ok(progress.percentage < 100)
})

test('completed artifacts show 100 percent and elapsed time stops at the server finish time', () => {
  const value = run('completed', 10)
  value.status = value.output_data.artifact_attempt.status = value.steps[0].status = 'completed'
  value.output_data.artifact_attempt.finished_time = '2026-10-17T00:02:03Z'
  const progress = lessonArtifactProgress(value, { now: Date.parse('2026-10-18T00:00:00Z') })
  assert.equal(progress.percentage, 100)
  assert.equal(progress.status, 'success')
  assert.equal(progress.elapsed, '已用时 2 分 3 秒')
})

test('the observed Beijing wall-clock timestamp counts elapsed time rather than staying at zero', () => {
  const value = run('illustrating', 0)
  value.output_data.artifact_attempt.started_time = '2026-10-17T10:44:28.039797'
  const now = Date.parse('2026-10-17T10:52:20.240+08:00')
  assert.equal(lessonArtifactProgress(value, { now }).elapsed, '已用时 7 分 52 秒')
  assert.equal(lessonArtifactProgress(value, { now: now + 1000 }).elapsed, '已用时 7 分 53 秒')
})

for (const start of ['2026-10-17T10:44:28+08:00', '2026-10-17T02:44:28Z', '2026-10-17T03:44:28+01:00']) {
  test(`explicit time offset is preserved: ${start}`, () => {
    const value = run()
    value.output_data.artifact_attempt.started_time = start
    assert.equal(lessonArtifactProgress(value, { now: Date.parse('2026-10-17T02:45:30Z') }).elapsed, '已用时 1 分 2 秒')
  })
}

test('legacy step timestamps also work when attempt metadata has no start time', () => {
  const value = run()
  delete value.output_data.artifact_attempt.started_time
  value.steps[0].started_time = '2026-10-17 10:44:28'
  assert.equal(lessonArtifactProgress(value, { now: Date.parse('2026-10-17T02:45:30Z') }).elapsed, '已用时 1 分 2 秒')
})

test('mixed legacy and explicit end timestamps stop the timer at completion', () => {
  const value = run('completed', 10)
  value.status = value.output_data.artifact_attempt.status = value.steps[0].status = 'completed'
  value.output_data.artifact_attempt.started_time = '2026-10-17T10:44:28'
  for (const end of ['2026-10-17T10:45:30', '2026-10-17T10:45:30+08:00', '2026-10-17T02:45:30Z']) {
    value.output_data.artifact_attempt.finished_time = end
    assert.equal(lessonArtifactProgress(value, { now: Date.parse('2026-10-18T00:00:00Z') }).elapsed, '已用时 1 分 2 秒')
  }
})

test('terminal fallback updated_time retains its UTC basis rather than using the agent wall-clock rule', () => {
  const value = run()
  value.status = value.steps[0].status = 'cancelled'
  value.output_data.artifact_attempt.started_time = '2026-10-17T10:44:28'
  value.updated_time = '2026-10-17T02:45:30'
  assert.equal(lessonArtifactProgress(value, { now: Date.parse('2026-10-18T00:00:00Z') }).elapsed, '已用时 1 分 2 秒')
})

for (const status of ['failed', 'partial', 'cancelled']) {
  test(`${status} never shows 100 percent or a green success`, () => {
    const value = run('completed', 10)
    value.status = status === 'cancelled' ? 'cancelled' : 'completed'
    value.output_data.artifact_attempt.status = status === 'cancelled' ? 'running' : status
    value.steps[0].status = status === 'cancelled' ? 'cancelled' : status === 'failed' ? 'failed' : 'completed'
    const progress = lessonArtifactProgress(value)
    assert.ok(progress.percentage < 100)
    assert.notEqual(progress.status, 'success')
    assert.equal(progress.active, false)
  })
}

test('invalid page counts are clamped and never produce NaN or overflow', () => {
  for (const [done, total] of [[NaN, 0], [-3, -4], [100, 10], [Infinity, Infinity]]) {
    const progress = lessonArtifactProgress(run('designing', done, total))
    assert.ok(Number.isFinite(progress.percentage))
    assert.ok(progress.percentage >= 0 && progress.percentage < 100)
    assert.doesNotMatch(progress.detail, /NaN|Infinity|剩余 -/)
  }
})

test('a single-image replacement does not display old artifact-generation success', () => {
  const value = run()
  value.output_data.ppt_image_job = { status: 'running' }
  assert.equal(lessonArtifactProgress(value), null)
})

test('non-PPT requests are supported without claiming a fake page count', () => {
  const value = run()
  value.output_data.artifact_attempt.requested_types = ['lesson_plan']
  value.steps[0].output_data = {}
  const progress = lessonArtifactProgress(value)
  assert.equal(progress.label, '正在生成教学文档')
  assert.doesNotMatch(progress.detail, /已设计/)
})

test('the artifact-generation UI uses measured progress and an explicit percentage', async () => {
  const source = await readFile(new URL('../src/views/LessonPrepWorkspaceView.vue', import.meta.url), 'utf8')
  const panel = source.split('class="artifact-generation-progress"')[1].split('</section>')[0]
  assert.match(panel, /artifactGenerationProgress\.percentage/)
  assert.match(panel, /stage|阶段进度/)
  assert.doesNotMatch(panel, /indeterminate|:percentage="58"/)
  assert.match(panel, /artifactGenerationProgress\.elapsed/)
  assert.match(panel, /artifactGenerationProgress\.detail/)
  for (const removed of ['不代表剩余时间比例', '系统会继续使用当前证据快照', '这些条件交给内容策划与视觉设计 Agent']) {
    assert.ok(!source.includes(removed))
  }
})

test('custom PPT names are editable before generation and version labels show the deck title, not the style', async () => {
  const source = await readFile(new URL('../src/views/LessonPrepWorkspaceView.vue', import.meta.url), 'utf8')
  const field = source.split('label="PPT 名称"')[1].split('</el-form-item>')[0]
  assert.match(field, /pptPreferences\.title/)
  assert.match(field, /maxlength="60"/)
  assert.match(field, /isExecuting/)
  assert.match(source, /title: pptPreferences\.value\.title\?\.trim\(\) \|\| null/)
  const currentVersion = source.split('\n').find(line => line.includes('value="current"'))
  assert.match(currentVersion, /artifactBundle\?\.ppt\?\.title/)
  assert.doesNotMatch(currentVersion, /design\?\.name/)
  const historyLabel = source.split('function versionLabel')[1].split('function versionReason')[0]
  assert.match(historyLabel, /item\.title/)
  assert.doesNotMatch(historyLabel, /item\.design_name/)
})
