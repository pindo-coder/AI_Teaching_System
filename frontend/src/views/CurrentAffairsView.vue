<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { aiApi, type AiAssistData } from '@/api/ai'
import { courseApi } from '@/api/courses'
import { getErrorMessage } from '@/utils/error'
import { newsApi, type NewsItem } from '@/api/news'
import type { CourseDetail } from '@/types'

const router = useRouter()
const loading = ref(false)
const newsLoading = ref(true)
const news = ref<NewsItem[]>([])
const textbook = ref<CourseDetail | null>(null)
const selectedNews = ref<NewsItem | null>(null)
const aiResult = ref<AiAssistData | null>(null)
const aiLoading = ref(false)
const aiMode = ref<'summary' | 'relation'>('summary')
const dialogVisible = ref(false)

onMounted(async () => {
  try {
    news.value = (await newsApi.list()).data.data
    const courses = (await courseApi.list()).data.data
    textbook.value = courses[0] ? (await courseApi.detail(courses[0].id)).data.data : null
  } finally { newsLoading.value = false }
})
async function openAi(item: NewsItem, mode: 'summary' | 'relation') {
  selectedNews.value = item
  aiMode.value = mode
  aiResult.value = null
  dialogVisible.value = true
  const course = textbook.value
  const chapter = course?.chapters[0]
  if (!course || !chapter) {
    ElMessage.warning('请先创建教材专题，再使用 AI 功能')
    return
  }
  aiLoading.value = true
  try {
    const question = mode === 'summary'
      ? `请用思政教材化表达总结以下时政信息，提炼核心事实、重要观点和学习关键词。标题：${item.title}；摘要：${item.summary || '无'}`
      : `请分析以下时政信息与当前教材专题的关系，指出对应的教材知识点并说明关联理由。标题：${item.title}；摘要：${item.summary || '无'}`
    const { data } = await aiApi.assist({ course_id: course.id, chapter_id: chapter.id, learning_stage: 'preview', task_type: mode === 'summary' ? 'question_answer' : 'question_answer', question })
    aiResult.value = data.data
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, 'AI 暂时无法生成结果'))
  } finally { aiLoading.value = false }
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-header">
      <div>
        <p class="eyebrow">时政要点</p>
        <h1>把现实议题讲回教材</h1>
        <p>围绕《习近平新时代中国特色社会主义思想概论》做时政主题导入、教材知识关联和课堂讨论生成。</p>
      </div>
      <el-button type="primary" @click="router.push('/courses')">返回课程总览</el-button>
    </header>

    <section class="affairs-layout affairs-layout-single">
      <div>
        <div class="section-heading"><div><p class="eyebrow">实时更新</p><h2>权威来源时政要点</h2></div></div>
        <el-card v-loading="newsLoading" shadow="never" class="news-list">
          <article v-for="item in news" :key="item.id" class="news-item"><div class="news-item-body"><h3>{{ item.title }}</h3><p>{{ item.summary || '打开原文查看详细内容。' }}</p><small>{{ item.source_name }} · {{ item.published_time ? new Date(item.published_time).toLocaleString() : '近期' }}</small><div class="news-actions"><el-button size="small" type="primary" plain @click="openAi(item, 'summary')">AI总结</el-button><el-button size="small" type="success" plain @click="openAi(item, 'relation')">关联课本</el-button></div></div><el-link :href="item.article_url" target="_blank" type="primary" :underline="false">查看原文 →</el-link></article>
          <el-empty v-if="!newsLoading && !news.length" description="暂未获取到时政信息，请稍后再试" />
        </el-card>
      </div>

    </section>
    <el-dialog v-model="dialogVisible" :title="aiMode === 'summary' ? 'AI 时政总结' : 'AI 课本关联'" width="680px"><div v-loading="aiLoading"><div v-if="selectedNews" class="selected-news"><strong>{{ selectedNews.title }}</strong><p>{{ selectedNews.summary || '暂无摘要' }}</p></div><div v-if="aiResult" class="ai-dialog-result"><el-tag :type="aiResult.grounded ? 'success' : 'warning'">{{ aiResult.grounded ? '依据教材资料生成' : '教材资料不足' }}</el-tag><div class="answer-content">{{ aiResult.answer }}</div></div><el-empty v-else-if="!aiLoading" description="暂无生成结果" /></div><template #footer><el-button @click="dialogVisible = false">关闭</el-button></template></el-dialog>
  </div>
</template>
