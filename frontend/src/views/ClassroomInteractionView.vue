<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Connection, Finished, Histogram, QuestionFilled } from '@element-plus/icons-vue'
import { courseApi } from '@/api/courses'
import type { CourseDetail } from '@/types'

const loading = ref(true)
const route = useRoute()
const textbook = ref<CourseDetail | null>(null)
const selectedChapterId = ref<number>()
const activity = reactive({ question: '中国式现代化为什么既有各国现代化的共同特征，又有基于自己国情的中国特色？', minutes: 8 })
const firstChapter = computed(() => textbook.value?.chapters.find((item) => item.id === selectedChapterId.value) || textbook.value?.chapters[0] || null)
const patterns = [
  { title: '随堂问答', desc: '围绕一个核心概念生成递进式提问。', icon: QuestionFilled },
  { title: '观点辨析', desc: '给出正误判断、理由说明和追问。', icon: ChatDotRound },
  { title: '小组讨论', desc: '按主题分组，产出讨论任务和汇报要求。', icon: Connection },
  { title: '即时反馈', desc: '记录课堂表现，形成课后巩固方向。', icon: Histogram },
]

onMounted(async () => {
  try {
    const list = (await courseApi.list()).data.data
    textbook.value = list[0] ? (await courseApi.detail(list[0].id)).data.data : null
    selectedChapterId.value = textbook.value?.chapters[0]?.id
    const newsTitle = typeof route.query.news_title === 'string' ? route.query.news_title : ''
    if (newsTitle) activity.question = `围绕时政“${newsTitle}”，联系教材专题开展课堂讨论。`
  } finally { loading.value = false }
})

function launchActivity() {
  if (!activity.question.trim()) return ElMessage.warning('请输入互动主题')
  ElMessage.success('课堂互动任务已生成，可继续用右侧 AI 完善话术')
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-header">
      <div>
        <p class="eyebrow">课堂互动</p>
        <h1>把专题学习变成可参与的课堂活动</h1>
        <p>面向教师备课和课堂使用，快速组织提问、辨析、讨论和即时反馈。</p>
      </div>
    </header>

    <section class="interaction-layout interaction-layout-single">
      <div>
        <section class="module-grid interaction-patterns">
          <el-card v-for="item in patterns" :key="item.title" shadow="never" class="module-card quiet-card">
            <el-icon :size="24"><component :is="item.icon" /></el-icon>
            <h3>{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
          </el-card>
        </section>

        <el-card shadow="never" class="interaction-builder">
          <template #header><div class="content-heading"><span>互动任务生成</span><el-tag type="success">MVP</el-tag></div></template>
          <el-form label-position="top">
            <el-form-item label="关联专题">
              <el-select v-model="selectedChapterId" placeholder="请选择专题">
                <el-option v-for="chapter in textbook?.chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="互动主题">
              <el-input v-model="activity.question" type="textarea" :rows="4" maxlength="500" show-word-limit />
            </el-form-item>
            <el-form-item label="建议时长">
              <el-input-number v-model="activity.minutes" :min="3" :max="30" />
              <span class="form-hint">分钟</span>
            </el-form-item>
          </el-form>
          <el-button type="primary" :icon="Finished" @click="launchActivity">生成课堂活动</el-button>
          <div class="activity-preview">
            <strong>活动预览</strong>
            <p>围绕“{{ activity.question }}”进行 {{ activity.minutes }} 分钟讨论：先独立思考，再小组交流，最后由教师引导回到教材专题“{{ firstChapter?.title || '未选择专题' }}”。</p>
          </div>
        </el-card>
      </div>

    </section>
  </div>
</template>
