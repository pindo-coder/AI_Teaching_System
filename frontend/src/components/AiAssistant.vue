<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick, Promotion } from '@element-plus/icons-vue'
import { aiApi, type AiAssistData, type AiTaskType } from '@/api/ai'
import type { LearningStage } from '@/types'
import { getErrorMessage } from '@/utils/error'

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

function choosePrompt(label: string, task: AiTaskType) {
  question.value = label
  taskType.value = task
}

async function submit() {
  if (!question.value.trim()) return ElMessage.warning('请输入需要 AI 辅助的问题')
  loading.value = true
  try {
    const { data } = await aiApi.assist({
      course_id: props.courseId,
      chapter_id: props.chapterId,
      learning_stage: props.learningStage,
      task_type: taskType.value,
      question: question.value.trim(),
    })
    result.value = data.data
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
      <div class="answer-content">{{ result.answer }}</div>
      <div v-if="result.sources.length" class="answer-sources"><strong>参考资料</strong><div v-for="source in result.sources" :key="source.source_title" class="source-item"><span>{{ source.source_title }}</span><p>{{ source.excerpt }}</p></div></div>
    </section>
  </el-card>
</template>
