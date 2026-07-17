<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick, Promotion } from '@element-plus/icons-vue'
import { aiApi, type AiAssistData, type AiTaskType } from '@/api/ai'
import type { LearningStage } from '@/types'
import { getErrorMessage } from '@/utils/error'
import { renderTeachingDocument } from '@/utils/richText'
import { learningApi } from '@/api/learning'
import PdfCitationViewer from '@/components/PdfCitationViewer.vue'
import type { AiSource } from '@/api/ai'

const props = defineProps<{
  courseId: number
  chapterId: number
  learningStage: LearningStage
}>()

const stageConfig = computed(() => ({
  preview: {
    title: 'AI 预习助手',
    description: '提前梳理章节结构，带着问题进入课堂。',
    prompts: [
      { label: '总结本章重点', task: 'chapter_summary' as AiTaskType },
      { label: '生成预习问题', task: 'preview_questions' as AiTaskType },
      { label: '解释核心概念', task: 'question_answer' as AiTaskType },
    ],
  },
  review: {
    title: 'AI 巩固助手',
    description: '依据章节资料回顾重点，形成结构化认识。',
    prompts: [
      { label: '生成复习提纲', task: 'review_outline' as AiTaskType },
      { label: '总结本章重点', task: 'chapter_summary' as AiTaskType },
      { label: '解答知识疑问', task: 'question_answer' as AiTaskType },
    ],
  },
  exam: {
    title: 'AI 冲刺助手',
    description: '围绕章节知识点进行考点梳理和模拟训练。',
    prompts: [
      { label: '生成模拟题', task: 'mock_questions' as AiTaskType },
      { label: '梳理重点考点', task: 'review_outline' as AiTaskType },
      { label: '检查知识盲点', task: 'question_answer' as AiTaskType },
    ],
  },
})[props.learningStage])

const question = ref('')
const taskType = ref<AiTaskType>('question_answer')
const loading = ref(false)
const result = ref<AiAssistData | null>(null)
const citationVisible = ref(false)
const selectedSource = ref<AiSource | null>(null)
const renderedAnswer = computed(() => renderTeachingDocument(result.value?.answer || ''))

function choosePrompt(label: string, task: AiTaskType) {
  question.value = label
  taskType.value = task
}

function openCitation(source: AiSource) {
  if (!source.document_id || !source.pdf_page_start) return
  selectedSource.value = source
  citationVisible.value = true
}

async function submit() {
  if (!question.value.trim()) return ElMessage.warning('请输入需要 AI 辅助的问题')
  loading.value = true
  try {
    result.value = { answer: '', grounded: true, model: '', sources: [] }
    await aiApi.assistStream({
      course_id: props.courseId,
      chapter_id: props.chapterId,
      learning_stage: props.learningStage,
      task_type: taskType.value,
      question: question.value.trim(),
    }, {
      onMeta: (meta) => { if (result.value) { result.value.grounded = meta.grounded; result.value.model = meta.model } },
      onChunk: (text) => { if (result.value) result.value.answer += text },
      onSources: (sources) => { if (result.value) result.value.sources = sources },
    })
    await learningApi.recordEvent({
      course_id: props.courseId,
      chapter_id: props.chapterId,
      learning_stage: props.learningStage,
      event_type: 'ai_assist_used',
      event_data: { task_type: taskType.value },
    })
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, 'AI 服务暂时不可用，请稍后重试'))
  } finally { loading.value = false }
}
</script>

<template>
  <el-card shadow="never" class="ai-assistant">
    <div class="ai-heading">
      <div class="ai-icon"><el-icon :size="24"><MagicStick /></el-icon></div>
      <div><h2>{{ stageConfig.title }}</h2><p>{{ stageConfig.description }}</p></div>
    </div>
    <div class="quick-prompts">
      <el-button v-for="item in stageConfig.prompts" :key="item.label" round @click="choosePrompt(item.label, item.task)">{{ item.label }}</el-button>
    </div>
    <div class="ai-input">
      <el-input v-model="question" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="请围绕当前章节提出问题……" @keydown.ctrl.enter="submit" />
      <el-button type="primary" :loading="loading" :icon="Promotion" @click="submit">发送</el-button>
    </div>
    <section v-if="result" class="ai-result">
      <div class="answer-meta"><el-tag :type="result.grounded ? 'success' : 'warning'" effect="light">{{ result.grounded ? '依据课程资料生成' : '课程资料不足' }}</el-tag><span>模型：{{ result.model }}</span></div>
      <article class="answer-content teaching-document" v-html="renderedAnswer"></article><span v-if="loading" class="stream-cursor" aria-label="正在生成"></span>
      <div v-if="result.sources.length" class="answer-sources"><div class="source-heading"><strong>原文依据与引用位置</strong><span>点击引用可核对教材原页</span></div><button v-for="(source, index) in result.sources" :key="`${source.source_title}-${index}`" type="button" class="source-item source-item--button" :disabled="!source.document_id || !source.pdf_page_start" @click="openCitation(source)"><div class="source-title"><span>[{{ index + 1 }}] {{ source.source_title }}</span><el-tag size="small" :type="source.evidence_type === '教材直接依据' ? 'success' : 'info'">{{ source.evidence_type }}</el-tag></div><strong class="source-position">{{ source.section_path || source.position }}</strong><p>{{ source.excerpt }}</p><span v-if="source.document_id && source.pdf_page_start" class="source-open">查看 PDF 原页 →</span></button></div>
    </section>
    <PdfCitationViewer v-model:visible="citationVisible" :source="selectedSource" />
  </el-card>
</template>
