<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Delete, EditPen, Link, MagicStick, Notebook, QuestionFilled, Reading, StarFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  studyApi,
  type TextbookAnnotation,
  type TextbookAnnotationCreate,
  type TextbookAnnotationType,
} from '@/api/study'
import { getErrorMessage } from '@/utils/error'
import { formatBeijingDateTime } from '@/utils/time'
import { requestWorkspaceAi } from '@/utils/workspaceAiEvents'
import type { LearningStage } from '@/types'

const props = withDefaults(defineProps<{
  chapterId: number
  courseId: number
  learningStage: LearningStage
  blocks: string[]
  readerLabel: string
  readerTitle?: string
  readerHint?: string
}>(), {
  readerTitle: '教材原文',
  readerHint: '选中文字即可添加标注',
})
const emit = defineEmits<{ scroll: [event: Event] }>()

type ResolvedAnnotation = TextbookAnnotation & { resolvedBlock: number; resolvedStart: number; resolvedEnd: number }
type Segment = { text: string; annotation: ResolvedAnnotation | null }
type SelectionDraft = TextbookAnnotationCreate & { toolbarLeft: number; toolbarTop: number }

const root = ref<HTMLElement | null>(null)
const readingElement = ref<HTMLElement | null>(null)
const annotations = ref<TextbookAnnotation[]>([])
const loading = ref(false)
const saving = ref(false)
const drawerVisible = ref(false)
const dialogVisible = ref(false)
const editingAnnotation = ref<TextbookAnnotation | null>(null)
const selectionDraft = ref<SelectionDraft | null>(null)
const annotationForm = reactive<{ annotation_type: TextbookAnnotationType; comment: string }>({
  annotation_type: 'key_point',
  comment: '',
})

const typeOptions: Array<{ value: TextbookAnnotationType; label: string }> = [
  { value: 'key_point', label: '重点' },
  { value: 'concept', label: '概念' },
  { value: 'question', label: '疑问' },
]
const typeLabels: Record<TextbookAnnotationType, string> = {
  key_point: '重点',
  concept: '概念',
  question: '疑问',
}
const annotationAiActions = [
  { label: '解释这段原文', instruction: '解释这段原文的含义、论述重点和理解线索。' },
  { label: '联系本章观点', instruction: '说明这段原文与当前专题核心观点之间的联系。' },
  { label: '辨析相关概念', instruction: '辨析这段原文涉及的核心概念及容易混淆之处。' },
  { label: '生成复习问题', instruction: '围绕这段原文生成 3 个有助于理解和复习的问题，并给出简要作答要点。' },
]

function allOccurrences(source: string, target: string): number[] {
  const output: number[] = []
  let cursor = 0
  while (target && cursor <= source.length - target.length) {
    const index = source.indexOf(target, cursor)
    if (index < 0) break
    output.push(index)
    cursor = index + Math.max(1, target.length)
  }
  return output
}

function resolveAnnotation(annotation: TextbookAnnotation): ResolvedAnnotation | null {
  const expectedBlock = props.blocks[annotation.block_index]
  if (expectedBlock?.slice(annotation.start_offset, annotation.end_offset) === annotation.selected_text) {
    return { ...annotation, resolvedBlock: annotation.block_index, resolvedStart: annotation.start_offset, resolvedEnd: annotation.end_offset }
  }

  const candidates: Array<{ block: number; start: number; score: number }> = []
  props.blocks.forEach((block, blockIndex) => {
    allOccurrences(block, annotation.selected_text).forEach((start) => {
      const prefix = block.slice(Math.max(0, start - annotation.prefix_text.length), start)
      const suffix = block.slice(start + annotation.selected_text.length, start + annotation.selected_text.length + annotation.suffix_text.length)
      let score = blockIndex === annotation.block_index ? 4 : 0
      if (annotation.prefix_text && prefix.endsWith(annotation.prefix_text)) score += 3
      if (annotation.suffix_text && suffix.startsWith(annotation.suffix_text)) score += 3
      score -= Math.min(2, Math.abs(start - annotation.start_offset) / 100)
      candidates.push({ block: blockIndex, start, score })
    })
  })
  candidates.sort((left, right) => right.score - left.score)
  const best = candidates[0]
  return best
    ? { ...annotation, resolvedBlock: best.block, resolvedStart: best.start, resolvedEnd: best.start + annotation.selected_text.length }
    : null
}

const resolvedAnnotations = computed(() => annotations.value.map(resolveAnnotation).filter((item): item is ResolvedAnnotation => Boolean(item)))
const unresolvedAnnotations = computed(() => annotations.value.filter((item) => !resolvedAnnotations.value.some((resolved) => resolved.id === item.id)))
const blockSegments = computed<Segment[][]>(() => props.blocks.map((block, blockIndex) => {
  const blockAnnotations = resolvedAnnotations.value
    .filter((item) => item.resolvedBlock === blockIndex)
    .sort((left, right) => left.resolvedStart - right.resolvedStart || right.resolvedEnd - left.resolvedEnd)
  const segments: Segment[] = []
  let cursor = 0
  for (const annotation of blockAnnotations) {
    if (annotation.resolvedStart < cursor || annotation.resolvedStart >= block.length) continue
    if (annotation.resolvedStart > cursor) segments.push({ text: block.slice(cursor, annotation.resolvedStart), annotation: null })
    const end = Math.min(block.length, annotation.resolvedEnd)
    segments.push({ text: block.slice(annotation.resolvedStart, end), annotation })
    cursor = end
  }
  if (cursor < block.length) segments.push({ text: block.slice(cursor), annotation: null })
  return segments
}))

async function loadAnnotations() {
  if (!props.chapterId) return
  loading.value = true
  try {
    annotations.value = (await studyApi.textbookAnnotations(props.chapterId)).data.data
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材标注加载失败'))
  } finally {
    loading.value = false
  }
}

function paragraphForNode(node: Node | null): HTMLElement | null {
  const element = node?.nodeType === Node.ELEMENT_NODE ? node as HTMLElement : node?.parentElement
  return element?.closest<HTMLElement>('[data-textbook-block]') || null
}

function offsetWithin(paragraph: HTMLElement, node: Node, offset: number): number {
  const range = document.createRange()
  range.selectNodeContents(paragraph)
  range.setEnd(node, offset)
  return range.toString().length
}

function captureSelection() {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !selection.rangeCount || !root.value) {
    selectionDraft.value = null
    return
  }
  const range = selection.getRangeAt(0)
  if (!root.value.contains(range.commonAncestorContainer)) {
    selectionDraft.value = null
    return
  }
  const startParagraph = paragraphForNode(range.startContainer)
  const endParagraph = paragraphForNode(range.endContainer)
  if (!startParagraph || startParagraph !== endParagraph) {
    selectionDraft.value = null
    ElMessage.warning('请在同一段教材原文内进行标注')
    return
  }
  const blockIndex = Number(startParagraph.dataset.textbookBlock)
  const block = props.blocks[blockIndex]
  if (!block) return
  let start = offsetWithin(startParagraph, range.startContainer, range.startOffset)
  let end = offsetWithin(startParagraph, range.endContainer, range.endOffset)
  if (start > end) [start, end] = [end, start]
  const rawText = block.slice(start, end)
  const leadingWhitespace = rawText.length - rawText.trimStart().length
  const trailingWhitespace = rawText.length - rawText.trimEnd().length
  start += leadingWhitespace
  end -= trailingWhitespace
  const selectedText = block.slice(start, end)
  if (!selectedText) return
  if (selectedText.length > 2000) {
    ElMessage.warning('单条标注不能超过 2000 字')
    return
  }
  const overlaps = resolvedAnnotations.value.some((item) => (
    item.resolvedBlock === blockIndex && item.resolvedStart < end && item.resolvedEnd > start
  ))
  if (overlaps) {
    selectionDraft.value = null
    ElMessage.warning('所选内容包含已有标注，请点击原标注进行编辑')
    return
  }
  const rect = range.getBoundingClientRect()
  const toolbarTop = rect.top > 68 ? rect.top - 10 : rect.bottom + 46
  selectionDraft.value = {
    block_index: blockIndex,
    start_offset: start,
    end_offset: end,
    selected_text: selectedText,
    prefix_text: block.slice(Math.max(0, start - 60), start),
    suffix_text: block.slice(end, end + 60),
    annotation_type: 'key_point',
    comment: '',
    toolbarLeft: Math.min(window.innerWidth - 150, Math.max(150, rect.left + rect.width / 2)),
    toolbarTop,
  }
}

function scheduleSelectionCapture() {
  window.setTimeout(captureSelection, 0)
}

function clearBrowserSelection() {
  window.getSelection()?.removeAllRanges()
}

function draftPayload(draft: SelectionDraft): TextbookAnnotationCreate {
  return {
    block_index: draft.block_index,
    start_offset: draft.start_offset,
    end_offset: draft.end_offset,
    selected_text: draft.selected_text,
    prefix_text: draft.prefix_text,
    suffix_text: draft.suffix_text,
    annotation_type: draft.annotation_type,
    comment: draft.comment,
  }
}

async function createQuickAnnotation(annotationType: TextbookAnnotationType) {
  if (!selectionDraft.value || saving.value) return
  saving.value = true
  try {
    const payload = { ...draftPayload(selectionDraft.value), annotation_type: annotationType }
    const created = (await studyApi.createTextbookAnnotation(props.chapterId, payload)).data.data
    annotations.value.push(created)
    selectionDraft.value = null
    clearBrowserSelection()
    ElMessage.success(`${typeLabels[annotationType]}标注已保存`)
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材标注保存失败'))
  } finally {
    saving.value = false
  }
}

function openCreateDialog() {
  if (!selectionDraft.value) return
  editingAnnotation.value = null
  annotationForm.annotation_type = 'key_point'
  annotationForm.comment = ''
  dialogVisible.value = true
}

function createToolbarAnnotation(annotationType: TextbookAnnotationType) {
  if (!selectionDraft.value) {
    ElMessage.info('请先在教材原文中选择文字')
    return
  }
  void createQuickAnnotation(annotationType)
}

function openAnnotation(annotation: TextbookAnnotation) {
  selectionDraft.value = null
  clearBrowserSelection()
  editingAnnotation.value = annotation
  annotationForm.annotation_type = annotation.annotation_type
  annotationForm.comment = annotation.comment
  dialogVisible.value = true
}

async function persistDialogAnnotation(): Promise<TextbookAnnotation | null> {
  if (editingAnnotation.value) {
    const updated = (await studyApi.updateTextbookAnnotation(editingAnnotation.value.id, {
      annotation_type: annotationForm.annotation_type,
      comment: annotationForm.comment,
    })).data.data
    const index = annotations.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) annotations.value[index] = updated
    return updated
  }
  if (selectionDraft.value) {
    const created = (await studyApi.createTextbookAnnotation(props.chapterId, {
      ...draftPayload(selectionDraft.value),
      annotation_type: annotationForm.annotation_type,
      comment: annotationForm.comment,
    })).data.data
    annotations.value.push(created)
    return created
  }
  return null
}

async function saveDialogAnnotation() {
  if (saving.value) return
  saving.value = true
  try {
    const wasEditing = Boolean(editingAnnotation.value)
    const annotation = await persistDialogAnnotation()
    if (!annotation) return
    ElMessage.success(wasEditing ? '教材标注已更新' : '教材标注已保存')
    dialogVisible.value = false
    selectionDraft.value = null
    clearBrowserSelection()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材标注保存失败'))
  } finally {
    saving.value = false
  }
}

function truncatePromptPart(value: string, limit: number) {
  const normalized = value.trim()
  return normalized.length > limit ? `${normalized.slice(0, limit - 1)}…` : normalized
}

function buildAnnotationAiPrompt(annotation: TextbookAnnotation, instruction: string) {
  const quote = truncatePromptPart(annotation.selected_text, 900)
  const comment = truncatePromptPart(annotation.comment, 600) || '暂未填写个人注释'
  return [
    '请严格依据当前专题教材完成下面的任务，不要脱离教材原文作无依据推断。',
    `任务：${instruction}`,
    `教材原文（选段）：\n「${quote}」`,
    `标注类型：${typeLabels[annotation.annotation_type]}`,
    `我的注释：${comment}`,
    '回答时请先回应我的注释或疑问，再说明教材依据。',
  ].join('\n\n').slice(0, 2000)
}

async function askAiAboutAnnotation(instruction: string) {
  if (saving.value) return
  saving.value = true
  try {
    const annotation = await persistDialogAnnotation()
    if (!annotation) return
    dialogVisible.value = false
    drawerVisible.value = false
    selectionDraft.value = null
    clearBrowserSelection()
    await nextTick()
    requestWorkspaceAi({
      courseId: props.courseId,
      chapterId: props.chapterId,
      learningStage: props.learningStage,
      taskType: 'question_answer',
      prompt: buildAnnotationAiPrompt(annotation, instruction),
    })
    ElMessage.success('标注已保存，问题已填入 AI 助教')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '教材标注保存失败'))
  } finally {
    saving.value = false
  }
}

async function deleteAnnotation(annotation: TextbookAnnotation) {
  try {
    await ElMessageBox.confirm('删除后无法恢复，是否继续？', '删除教材标注', { type: 'warning' })
    await studyApi.deleteTextbookAnnotation(annotation.id)
    annotations.value = annotations.value.filter((item) => item.id !== annotation.id)
    dialogVisible.value = false
    ElMessage.success('教材标注已删除')
  } catch (error: unknown) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '教材标注删除失败'))
  }
}

async function locateAnnotation(annotation: TextbookAnnotation) {
  drawerVisible.value = false
  await nextTick()
  const target = readingElement.value?.querySelector<HTMLElement>(`[data-annotation-id="${annotation.id}"]`)
  if (!target) return ElMessage.warning('教材原文已更新，这条标注暂时无法定位')
  target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  target.classList.add('is-located')
  window.setTimeout(() => target.classList.remove('is-located'), 1600)
}

function dismissSelection(event: PointerEvent) {
  const target = event.target
  if (!(target instanceof Node)) return
  if (target instanceof Element && target.closest('.annotation-selection-toolbar')) return
  selectionDraft.value = null
}

function handleReadingScroll(event: Event) {
  selectionDraft.value = null
  emit('scroll', event)
}

function closeAnnotationDialog() {
  editingAnnotation.value = null
  selectionDraft.value = null
  clearBrowserSelection()
}

watch(() => props.chapterId, () => {
  annotations.value = []
  selectionDraft.value = null
  void loadAnnotations()
})
onMounted(() => {
  void loadAnnotations()
  document.addEventListener('pointerdown', dismissSelection)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', dismissSelection))

defineExpose({ getElement: () => readingElement.value })
</script>

<template>
  <div ref="root" v-loading="loading" class="textbook-annotation-reader">
    <div class="annotation-reader-toolbar" :title="props.readerHint">
      <div class="annotation-reader-title"><el-icon><Reading /></el-icon><strong>{{ props.readerTitle }}</strong></div>
      <div class="annotation-reader-tools" aria-label="三种标注方式" @pointerdown.stop>
        <button type="button" class="annotation-type-button is-key_point" title="标注重点" aria-label="标注重点" @click="createToolbarAnnotation('key_point')"><el-icon><StarFilled /></el-icon><span>重点</span></button>
        <button type="button" class="annotation-type-button is-concept" title="标注概念" aria-label="标注概念" @click="createToolbarAnnotation('concept')"><el-icon><Link /></el-icon><span>概念</span></button>
        <button type="button" class="annotation-type-button is-question" title="标注疑问" aria-label="标注疑问" @click="createToolbarAnnotation('question')"><el-icon><QuestionFilled /></el-icon><span>疑问</span></button>
        <span class="annotation-reader-divider" aria-hidden="true"></span>
        <el-button :icon="Notebook" plain size="small" @click="drawerVisible = true">我的标注 {{ annotations.length }}</el-button>
      </div>
    </div>
    <article
      ref="readingElement"
      class="chapter-text textbook-document textbook-scroll-window annotation-document"
      tabindex="0"
      :aria-label="readerLabel"
      @scroll.passive="handleReadingScroll"
      @mouseup="scheduleSelectionCapture"
      @touchend="scheduleSelectionCapture"
      @keyup="scheduleSelectionCapture"
    >
      <p v-for="(segments, blockIndex) in blockSegments" :key="blockIndex" :data-textbook-block="blockIndex">
        <template v-for="(segment, segmentIndex) in segments" :key="`${blockIndex}-${segmentIndex}`">
          <mark
            v-if="segment.annotation"
            class="textbook-annotation-mark"
            :class="`is-${segment.annotation.annotation_type}`"
            :data-annotation-id="segment.annotation.id"
            :title="segment.annotation.comment || `${typeLabels[segment.annotation.annotation_type]}标注`"
            @click.stop="openAnnotation(segment.annotation)"
          >{{ segment.text }}</mark><template v-else>{{ segment.text }}</template>
        </template>
      </p>
    </article>

    <div
      v-if="selectionDraft"
      class="annotation-selection-toolbar"
      :style="{ left: `${selectionDraft.toolbarLeft}px`, top: `${selectionDraft.toolbarTop}px` }"
      @pointerdown.stop.prevent
    >
      <button v-for="option in typeOptions" :key="option.value" type="button" :class="`is-${option.value}`" :disabled="saving" @click="createQuickAnnotation(option.value)">{{ option.label }}</button>
      <button type="button" class="with-comment" :disabled="saving" @click="openCreateDialog"><el-icon><EditPen /></el-icon><span>注释</span></button>
    </div>

    <el-drawer v-model="drawerVisible" title="我的专题标注" size="min(420px, 100%)">
      <div v-if="annotations.length" class="annotation-list">
        <article v-for="annotation in annotations" :key="annotation.id" class="annotation-list-item" :class="`is-${annotation.annotation_type}`">
          <button type="button" @click="locateAnnotation(annotation)">
            <span>{{ typeLabels[annotation.annotation_type] }} · {{ formatBeijingDateTime(annotation.updated_time) }}</span>
            <strong>“{{ annotation.selected_text }}”</strong>
            <p v-if="annotation.comment">{{ annotation.comment }}</p>
            <small v-if="unresolvedAnnotations.some((item) => item.id === annotation.id)">原文已更新，暂时无法定位</small>
          </button>
          <el-button text :icon="EditPen" title="编辑标注" aria-label="编辑标注" @click="openAnnotation(annotation)" />
        </article>
      </div>
      <el-empty v-else description="本专题还没有个人标注" />
    </el-drawer>

    <el-dialog v-model="dialogVisible" :title="editingAnnotation ? '编辑教材标注' : '添加教材注释'" width="min(520px, 92vw)" append-to-body @closed="closeAnnotationDialog">
      <div class="annotation-dialog-scroll">
        <blockquote class="annotation-quote">{{ editingAnnotation?.selected_text || selectionDraft?.selected_text }}</blockquote>
        <el-form label-position="top">
          <el-form-item label="标注类型">
            <el-radio-group v-model="annotationForm.annotation_type">
              <el-radio-button v-for="option in typeOptions" :key="option.value" :value="option.value">{{ option.label }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="个人注释">
            <el-input v-model="annotationForm.comment" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="记录你的理解、疑问或复习提示" />
          </el-form-item>
        </el-form>
        <section class="annotation-ai-section">
          <header><el-icon><MagicStick /></el-icon><div><strong>快捷询问 AI</strong><span>保存标注后，将问题填入顶部 AI 助教</span></div></header>
          <div class="annotation-ai-actions">
            <el-button v-for="action in annotationAiActions" :key="action.label" plain :disabled="saving" @click="askAiAboutAnnotation(action.instruction)">{{ action.label }}</el-button>
          </div>
        </section>
      </div>
      <template #footer>
        <div class="annotation-dialog-footer">
          <el-button v-if="editingAnnotation" type="danger" plain :icon="Delete" @click="deleteAnnotation(editingAnnotation)">删除</el-button>
          <span v-else></span>
          <div><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveDialogAnnotation">保存</el-button></div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.textbook-annotation-reader { min-width: 0; }
.annotation-reader-toolbar { display: flex; min-height: 66px; align-items: center; gap: 16px; margin: -30px -38px 24px; padding: 12px 20px; background: #fff8f8; border-bottom: 1px solid #f0dde0; }
.annotation-reader-title { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 10px; color: #ff2b35; font-size: 23px; }
.annotation-reader-title .el-icon { font-size: 31px; }
.annotation-reader-tools { display: flex; flex: 0 0 auto; align-items: center; gap: 4px; }
.annotation-type-button { display: inline-flex; min-width: 62px; height: 36px; align-items: center; justify-content: center; gap: 5px; padding: 0 10px; border: 1px solid transparent; border-radius: 9px; cursor: pointer; font: inherit; font-size: 13px; font-weight: 700; transition: transform .16s ease, box-shadow .16s ease; }
.annotation-type-button:hover { transform: translateY(-1px); box-shadow: 0 4px 10px rgb(55 40 64 / 10%); }
.annotation-type-button:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
.annotation-type-button .el-icon { font-size: 17px; }
.annotation-type-button.is-key_point { color: #956216; background: #fff4c7; border-color: #f3d982; }
.annotation-type-button.is-concept { color: #276579; background: #e0f3f6; border-color: #b3dfe7; }
.annotation-type-button.is-question { color: #9a4355; background: #ffe3e8; border-color: #f0b8c4; }
.annotation-reader-divider { width: 1px; height: 24px; margin: 0 6px; background: #e8dce3; }
.annotation-reader-tools :deep(.el-button) { min-width: 110px; flex: 0 0 auto; height: 36px; margin: 0; padding: 0 8px; color: #655d68; border-color: #d9d0dc; border-radius: 9px; font-size: 14px; font-weight: 650; white-space: nowrap; }
.annotation-reader-tools :deep(.el-button:hover) { color: #ff2b35; border-color: #ffb3b8; background: #fff5f5; }
.annotation-reader-tools :deep(.el-button .el-icon) { font-size: 17px; }
.annotation-document { position: relative; }
.textbook-annotation-mark { padding: 1px 2px; color: inherit; border-radius: 3px; cursor: pointer; box-decoration-break: clone; -webkit-box-decoration-break: clone; transition: box-shadow .2s ease; }
.textbook-annotation-mark.is-key_point { background: #fff0a6; box-shadow: inset 0 -2px #e5b94f; }
.textbook-annotation-mark.is-concept { background: #d6f0f4; box-shadow: inset 0 -2px #63aebc; }
.textbook-annotation-mark.is-question { background: #ffdee4; box-shadow: inset 0 -2px #db7b8d; }
.textbook-annotation-mark:hover { box-shadow: inset 0 -3px currentColor; }
.textbook-annotation-mark.is-located { animation: annotation-locate 1.6s ease; }
.annotation-selection-toolbar { position: fixed; z-index: 2200; display: flex; align-items: center; gap: 3px; padding: 5px; background: #fff; border: 1px solid #dfe5ee; border-radius: 7px; box-shadow: 0 10px 28px rgb(35 49 73 / 20%); transform: translate(-50%, -100%); }
.annotation-selection-toolbar button { display: inline-flex; min-width: 42px; height: 30px; align-items: center; justify-content: center; gap: 4px; padding: 0 8px; color: #44536a; background: transparent; border: 0; border-radius: 4px; cursor: pointer; font: inherit; font-size: 12px; }
.annotation-selection-toolbar button:hover { background: #f3f5f8; }
.annotation-selection-toolbar .is-key_point:hover { background: #fff4bf; }
.annotation-selection-toolbar .is-concept:hover { background: #dff3f6; }
.annotation-selection-toolbar .is-question:hover { background: #ffe4e8; }
.annotation-selection-toolbar .with-comment { border-left: 1px solid #e4e8ef; border-radius: 0 4px 4px 0; }
.annotation-list { display: grid; gap: 10px; }
.annotation-list-item { display: grid; grid-template-columns: minmax(0, 1fr) 34px; align-items: start; border: 1px solid var(--line); border-left-width: 4px; border-radius: 6px; }
.annotation-list-item.is-key_point { border-left-color: #d9ad41; }
.annotation-list-item.is-concept { border-left-color: #54a2b2; }
.annotation-list-item.is-question { border-left-color: #d2697e; }
.annotation-list-item > button { display: grid; min-width: 0; gap: 6px; padding: 12px; color: inherit; text-align: left; background: transparent; border: 0; cursor: pointer; }
.annotation-list-item > button:hover strong { color: var(--action-blue); }
.annotation-list-item span, .annotation-list-item small { color: var(--ink-400); font-size: 11px; }
.annotation-list-item strong { overflow: hidden; color: var(--ink-800); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.annotation-list-item p { margin: 0; color: var(--ink-600); font-size: 12px; line-height: 1.6; }
.annotation-list-item small { color: var(--authority-red); }
.annotation-quote { max-height: 150px; margin: 0 0 18px; padding: 12px 14px; overflow-y: auto; color: var(--ink-700); background: var(--surface-soft); border: 0; border-left: 3px solid var(--highlight-gold); line-height: 1.7; }
.annotation-dialog-scroll { max-height: min(580px, calc(100vh - 220px)); overflow-y: auto; padding-right: 4px; overscroll-behavior: contain; }
.annotation-ai-section { padding: 14px; background: #f7f9fd; border: 1px solid #e0e7f2; border-radius: 7px; }
.annotation-ai-section header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; color: #315fbd; }
.annotation-ai-section header > .el-icon { font-size: 20px; }
.annotation-ai-section header div { display: grid; min-width: 0; gap: 2px; }
.annotation-ai-section header strong { color: var(--ink-800); font-size: 14px; }
.annotation-ai-section header span { color: var(--ink-400); font-size: 11px; }
.annotation-ai-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.annotation-ai-actions :deep(.el-button) { width: 100%; min-width: 0; margin: 0; }
.annotation-dialog-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.annotation-dialog-footer > div { display: flex; gap: 8px; }
.annotation-dialog-footer :deep(.el-button + .el-button) { margin-left: 0; }
@keyframes annotation-locate { 0%, 100% { outline: 0 solid transparent; } 30% { outline: 5px solid rgb(229 185 79 / 30%); } }
@media (max-width: 600px) {
  .annotation-reader-toolbar { min-height: 0; align-items: flex-start; flex-wrap: wrap; gap: 10px; margin: -30px -20px 20px; padding: 12px 16px; }
  .annotation-reader-title { font-size: 20px; }
  .annotation-reader-title .el-icon { font-size: 26px; }
  .annotation-reader-tools { margin-left: auto; }
  .annotation-selection-toolbar { max-width: calc(100vw - 16px); overflow-x: auto; }
  .annotation-dialog-scroll { max-height: calc(100dvh - 210px); }
  .annotation-ai-actions { grid-template-columns: 1fr; }
  .annotation-dialog-footer { align-items: stretch; flex-direction: column-reverse; }
  .annotation-dialog-footer > div { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .annotation-dialog-footer :deep(.el-button) { width: 100%; margin: 0; }
}

</style>
