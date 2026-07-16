<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { aiApi, type AiAssistData } from '@/api/ai'
import { courseApi } from '@/api/courses'
import { getErrorMessage } from '@/utils/error'
import { newsApi, type NewsItem, type TextbookRelationItem } from '@/api/news'
import { studyApi } from '@/api/study'
import type { CourseDetail } from '@/types'
import { renderTeachingDocument } from '@/utils/richText'
import { Refresh, Search } from '@element-plus/icons-vue'

const router = useRouter()
const loading = ref(false)
const newsLoading = ref(true)
const news = ref<NewsItem[]>([])
const availableSources = ref<string[]>([])
const searchKeyword = ref('')
const selectedSources = ref<string[]>([])
const timeDays = ref<number | null>(null)
const sortBy = ref<'latest' | 'relevance'>('latest')
const currentPage = ref(1)
const pageSize = ref(10)
const totalNews = ref(0)
const textbook = ref<CourseDetail | null>(null)
const selectedNews = ref<NewsItem | null>(null)
const aiResult = ref<AiAssistData | null>(null)
const aiLoading = ref(false)
const aiMode = ref<'summary' | 'relation'>('summary')
const dialogVisible = ref(false)
const studyDialogVisible = ref(false)
const refreshing = ref(false)
const relationLoading = ref(false)
const relations = ref<TextbookRelationItem[]>([])
const selectedChapterId = ref<number | null>(null)
const selectedRelation = computed(() => relations.value.find((item) => item.chapter_id === selectedChapterId.value) || null)
const studyDraft = ref('')
const draftLoading = ref(false)
const noteSaving = ref(false)
const noteExists = ref(false)
const savedChapterId = ref<number | null>(null)
let lastNewsLoadedAt = 0
const renderedAnswer = computed(() => renderTeachingDocument(aiResult.value?.answer || ''))
const sourceNames = computed(() => availableSources.value.length ? availableSources.value : [...new Set(news.value.map((item) => item.source_name))])
const hasFilters = computed(() => Boolean(searchKeyword.value.trim() || selectedSources.value.length || timeDays.value))

async function loadNews(resetPage = false) {
  if (resetPage) currentPage.value = 1
  newsLoading.value = true
  try {
    const result = (await newsApi.search({
      q: searchKeyword.value.trim(),
      sources: selectedSources.value,
      days: timeDays.value,
      sort: sortBy.value,
      page: currentPage.value,
      pageSize: pageSize.value,
    })).data.data
    news.value = result.items
    totalNews.value = result.total
    availableSources.value = result.sources
    lastNewsLoadedAt = Date.now()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '时政检索失败，请稍后重试'))
  } finally { newsLoading.value = false }
}
async function refreshNews() {
  refreshing.value = true
  try {
    await newsApi.refresh()
    await loadNews(true)
    lastNewsLoadedAt = Date.now()
    ElMessage.success('已更新时政，并按当前条件重新检索')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '刷新失败，请稍后重试'))
  } finally { refreshing.value = false }
}
function toggleSource(source: string) {
  selectedSources.value = selectedSources.value.includes(source)
    ? selectedSources.value.filter((item) => item !== source)
    : [...selectedSources.value, source]
  void loadNews(true)
}
function clearSources() {
  selectedSources.value = []
  void loadNews(true)
}
function resetSearch() {
  searchKeyword.value = ''
  selectedSources.value = []
  timeDays.value = null
  sortBy.value = 'latest'
  void loadNews(true)
}
function changePage(page: number) {
  currentPage.value = page
  void loadNews()
}
async function loadTextbook() {
  try {
    const courses = (await courseApi.list()).data.data
    textbook.value = courses[0] ? (await courseApi.detail(courses[0].id)).data.data : null
  } catch { /* 教材尚未导入时保持空状态 */ }
}
function refreshWhenReturning() {
  if (document.visibilityState === 'visible' && Date.now() - lastNewsLoadedAt > 30 * 60 * 1000) void loadNews()
}
onMounted(() => {
  void loadNews()
  void loadTextbook()
  document.addEventListener('visibilitychange', refreshWhenReturning)
})
onUnmounted(() => document.removeEventListener('visibilitychange', refreshWhenReturning))
async function openAi(item: NewsItem, mode: 'summary' | 'relation') {
  selectedNews.value = item
  aiMode.value = mode
  aiResult.value = null
  dialogVisible.value = true
  const course = textbook.value
  let chapter = course?.chapters[0]
  if (!course || !chapter) {
    ElMessage.warning('请先创建教材专题，再使用 AI 功能')
    return
  }
  aiLoading.value = true
  try {
    let relationHint = ''
    if (mode === 'relation') {
      const recommended = (await newsApi.textbookRelations(item.id, course.id)).data.data[0]
      const matched = recommended ? course.chapters.find((candidate) => candidate.id === recommended.chapter_id) : null
      if (matched) chapter = matched
      if (recommended) relationHint = `系统初步匹配位置：${recommended.position}；匹配线索：${recommended.reason}。`
    }
    const question = mode === 'summary'
      ? `请用思政教材化表达总结以下时政信息，提炼核心事实、重要观点和学习关键词。标题：${item.title}；摘要：${item.summary || '无'}`
      : `请分析以下时政信息与当前教材专题的关系，指出对应的教材知识点并说明关联理由。${relationHint}标题：${item.title}；摘要：${item.summary || '无'}`
    aiResult.value = { answer: '', grounded: true, model: '', sources: [] }
    await aiApi.assistStream({
      course_id: course.id,
      chapter_id: chapter.id,
      learning_stage: 'preview',
      task_type: 'question_answer',
      question,
    }, {
      onMeta: (meta) => { if (aiResult.value) { aiResult.value.grounded = meta.grounded; aiResult.value.model = meta.model } },
      onChunk: (text) => { if (aiResult.value) aiResult.value.answer += text },
      onSources: (sources) => { if (aiResult.value) aiResult.value.sources = sources },
    })
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, 'AI 暂时无法生成结果'))
  } finally { aiLoading.value = false }
}

async function openStudyNote(item: NewsItem) {
  const course = textbook.value
  if (!course) return ElMessage.warning('请先导入教材并生成专题章节')
  selectedNews.value = item
  studyDialogVisible.value = true
  relations.value = []
  selectedChapterId.value = null
  studyDraft.value = ''
  savedChapterId.value = null
  relationLoading.value = true
  try {
    relations.value = (await newsApi.textbookRelations(item.id, course.id)).data.data
    selectedChapterId.value = relations.value[0]?.chapter_id || course.chapters[0]?.id || null
    await checkNoteStatus()
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '暂时无法匹配教材章节'))
  } finally { relationLoading.value = false }
}

async function checkNoteStatus() {
  if (!selectedChapterId.value) return noteExists.value = false
  try { noteExists.value = Boolean((await studyApi.note(selectedChapterId.value)).data.data) }
  catch { noteExists.value = false }
}

async function generateStudyDraft() {
  const course = textbook.value
  const item = selectedNews.value
  const relation = selectedRelation.value
  if (!course || !item || !relation) return ElMessage.warning('请先选择关联的教材章节')
  studyDraft.value = ''
  savedChapterId.value = null
  draftLoading.value = true
  const question = [
    `请把以下时政材料整理为可供学生修改的研学笔记。`,
    `时政标题：${item.title}`,
    `时政摘要：${item.summary || '原始摘要未提供，请勿补写未知事实。'}`,
    `媒体来源：${item.source_name}`,
    `原文链接：${item.article_url}`,
    `教材匹配位置：${relation.position}`,
    `匹配理由：${relation.reason}`,
    `请严格区分时政事实、教材观点和启发性思考，并保留资料来源。`,
  ].join('\n')
  try {
    await aiApi.assistStream({
      course_id: course.id,
      chapter_id: relation.chapter_id,
      learning_stage: 'review',
      task_type: 'news_study_note',
      question,
    }, {
      onMeta: () => {},
      onChunk: (text) => { studyDraft.value += text },
      onSources: () => {},
    })
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '研学笔记生成失败，请稍后重试'))
  } finally { draftLoading.value = false }
}

async function saveStudyNote() {
  const item = selectedNews.value
  const relation = selectedRelation.value
  if (!item || !relation || !studyDraft.value.trim()) return ElMessage.warning('请先生成或填写研学笔记草稿')
  noteSaving.value = true
  try {
    const result = (await newsApi.saveStudyNote(item.id, {
      chapter_id: relation.chapter_id,
      content: studyDraft.value,
      textbook_relation: `${relation.position}；${relation.reason}`,
      mode: noteExists.value ? 'append' : 'create',
    })).data.data
    savedChapterId.value = result.chapter_id
    noteExists.value = true
    ElMessage.success(result.appended ? '已追加到该章节的个人笔记' : '已创建研学笔记')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '研学笔记保存失败'))
  } finally { noteSaving.value = false }
}

function openSavedNote() {
  if (!savedChapterId.value) return
  void router.push({ path: '/notes', query: { chapter_id: String(savedChapterId.value) } })
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
        <div class="section-heading"><div><p class="eyebrow">实时更新 · {{ sourceNames.length }} 个来源</p><h2>权威来源时政要点</h2></div><el-button :icon="Refresh" :loading="refreshing" plain type="primary" @click="refreshNews">刷新时政</el-button></div>
        <section class="news-search-panel">
          <div class="news-search-row">
            <el-input v-model="searchKeyword" :prefix-icon="Search" clearable placeholder="搜索政策、主题或关键词，例如：生态文明" @keyup.enter="loadNews(true)" @clear="loadNews(true)" />
            <el-select v-model="timeDays" placeholder="发布时间" clearable @change="loadNews(true)">
              <el-option label="最近 24 小时" :value="1" />
              <el-option label="最近 3 天" :value="3" />
              <el-option label="最近 7 天" :value="7" />
              <el-option label="最近 30 天" :value="30" />
              <el-option label="最近 90 天" :value="90" />
            </el-select>
            <el-select v-model="sortBy" @change="loadNews(true)">
              <el-option label="按时间排序" value="latest" />
              <el-option label="按相关度排序" value="relevance" :disabled="!searchKeyword.trim()" />
            </el-select>
            <el-button type="primary" :icon="Search" :loading="newsLoading" @click="loadNews(true)">搜索</el-button>
            <el-button v-if="hasFilters" @click="resetSearch">重置</el-button>
          </div>
          <div v-if="sourceNames.length" class="news-source-filter">
            <span>媒体来源</span>
            <el-check-tag :checked="selectedSources.length === 0" @change="clearSources">全部</el-check-tag>
            <el-check-tag v-for="source in sourceNames" :key="source" :checked="selectedSources.includes(source)" @change="toggleSource(source)">{{ source }}</el-check-tag>
          </div>
          <div class="news-search-summary"><span>共找到 <strong>{{ totalNews }}</strong> 条时政内容</span><span v-if="hasFilters">当前条件仅筛选已采集的权威资讯</span></div>
        </section>
        <el-card v-loading="newsLoading" shadow="never" class="news-list">
          <article v-for="item in news" :key="item.id" class="news-item"><div class="news-item-body"><h3>{{ item.title }}</h3><p>{{ item.summary || '打开原文查看详细内容。' }}</p><small><el-tag size="small" effect="plain">{{ item.source_name }}</el-tag> {{ item.published_time ? new Date(item.published_time).toLocaleString() : '近期' }}</small><div class="news-actions"><el-button size="small" type="primary" plain @click="openAi(item, 'summary')">AI总结</el-button><el-button size="small" type="success" plain @click="openAi(item, 'relation')">关联课本</el-button><el-button size="small" type="warning" plain @click="openStudyNote(item)">生成研学笔记</el-button></div></div><el-link :href="item.article_url" target="_blank" type="primary" :underline="false">查看原文 →</el-link></article>
          <el-empty v-if="!newsLoading && !news.length" description="暂未获取到时政信息，请稍后再试" />
        </el-card>
        <el-pagination v-if="totalNews > pageSize" class="news-pagination" background layout="prev, pager, next" :current-page="currentPage" :page-size="pageSize" :total="totalNews" @current-change="changePage" />
      </div>

    </section>
    <el-dialog v-model="dialogVisible" :title="aiMode === 'summary' ? 'AI 时政总结' : 'AI 课本关联'" width="720px">
      <div v-if="selectedNews" class="selected-news"><strong>{{ selectedNews.title }}</strong><p>{{ selectedNews.summary || '暂无摘要' }}</p></div>
      <section v-if="aiResult" class="ai-dialog-result ai-result">
        <div class="answer-meta"><el-tag :type="aiResult.grounded ? 'success' : 'warning'" effect="light">{{ aiResult.grounded ? '依据教材资料生成' : '教材资料不足' }}</el-tag><span v-if="aiResult.model">模型：{{ aiResult.model }}</span></div>
        <article class="answer-content teaching-document" v-html="renderedAnswer"></article><span v-if="aiLoading" class="stream-cursor" aria-label="正在生成"></span>
        <div v-if="aiResult.sources.length" class="answer-sources"><div class="source-heading"><strong>原文依据与引用位置</strong><span>回答仅依据以下课程资料</span></div><div v-for="(source, index) in aiResult.sources" :key="`${source.source_title}-${index}`" class="source-item"><div class="source-title"><span>[{{ index + 1 }}] {{ source.source_title }}</span><el-tag size="small" type="info">{{ source.position }}</el-tag></div><p>{{ source.excerpt }}</p></div></div>
      </section>
      <el-empty v-else-if="!aiLoading" description="暂无生成结果" />
      <template #footer><el-button @click="dialogVisible = false">关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="studyDialogVisible" title="生成时政研学笔记" width="880px" class="study-note-dialog">
      <div v-if="selectedNews" class="selected-news"><strong>{{ selectedNews.title }}</strong><p>{{ selectedNews.summary || '暂无摘要，请以原文为准。' }}</p></div>
      <div class="study-note-steps">
        <section v-loading="relationLoading" class="study-note-step">
          <div class="step-title"><span>1</span><div><strong>确认教材章节</strong><small>系统推荐不替代人工判断，可切换后再生成</small></div></div>
          <el-radio-group v-model="selectedChapterId" class="relation-options" @change="checkNoteStatus">
            <el-radio v-for="relation in relations" :key="relation.chapter_id" :value="relation.chapter_id" border>
              <strong>{{ relation.chapter_title }}</strong><span>{{ relation.reason }}</span><small>{{ relation.position }}</small>
            </el-radio>
          </el-radio-group>
          <el-alert v-if="selectedRelation" :closable="false" type="info" show-icon>
            <template #title>教材依据：{{ selectedRelation.excerpt }}</template>
          </el-alert>
        </section>
        <section class="study-note-step">
          <div class="step-title"><span>2</span><div><strong>生成并修改草稿</strong><small>事实来自新闻，理论观点限定在所选章节</small></div><el-button type="primary" :loading="draftLoading" :disabled="!selectedRelation" @click="generateStudyDraft">{{ studyDraft ? '重新生成' : '生成草稿' }}</el-button></div>
          <el-input v-model="studyDraft" type="textarea" :autosize="{ minRows: 12, maxRows: 20 }" maxlength="16000" show-word-limit placeholder="生成后可在这里增删、改写；保存后还能在笔记空间继续排版。" />
          <span v-if="draftLoading" class="stream-cursor" aria-label="正在生成"></span>
        </section>
        <section class="study-note-step save-study-note-row">
          <div class="step-title"><span>3</span><div><strong>{{ noteExists ? '追加到已有章节笔记' : '创建章节笔记' }}</strong><small>不会覆盖原笔记，并记录新闻来源与教材关联</small></div></div>
          <div><el-button v-if="savedChapterId" @click="openSavedNote">前往笔记空间修改</el-button><el-button type="success" :loading="noteSaving" :disabled="!studyDraft.trim() || draftLoading" @click="saveStudyNote">{{ noteExists ? '追加到笔记' : '添加到笔记空间' }}</el-button></div>
        </section>
      </div>
      <template #footer><el-button @click="studyDialogVisible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>
