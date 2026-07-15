<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Calendar, Reading } from '@element-plus/icons-vue'
import { studyApi, type ReviewAnswerResult, type ReviewItem, type ReviewQuestion } from '@/api/study'

const router = useRouter()
const loading = ref(true)
const reviews = ref<ReviewItem[]>([])
const active = ref<ReviewItem | null>(null)
const dialogVisible = ref(false)
const questions = ref<ReviewQuestion[]>([])
const currentIndex = ref(0)
const answer = ref('')
const result = ref<ReviewAnswerResult | null>(null)
const generating = ref(false)

async function load() {
  loading.value = true
  try { reviews.value = (await studyApi.reviews()).data.data } finally { loading.value = false }
}
async function begin(item: ReviewItem) {
  active.value = item; dialogVisible.value = true; questions.value = []; currentIndex.value = 0; answer.value = ''; result.value = null; generating.value = true
  try { questions.value = (await studyApi.reviewQuestions(item.chapter_id)).data.data } finally { generating.value = false }
}
async function submit() {
  const current = questions.value[currentIndex.value]
  if (!current || !answer.value.trim()) return ElMessage.warning('请先完成本题作答')
  result.value = (await studyApi.submitReviewAnswer(current.id, answer.value)).data.data
}
async function next() {
  if (!result.value) return
  if (result.value.completed) {
    ElMessage.success(`本次复习完成，${result.value.next_interval_days} 天后再次提醒`)
    active.value = null; dialogVisible.value = false; await load(); return
  }
  currentIndex.value += 1; answer.value = ''; result.value = null
}
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <header class="page-header"><div><p class="eyebrow">Spaced Review</p><h1>今日复习</h1><p>按照 1、2、4、7、15、30 天间隔巩固已经学习的教材专题。</p></div><el-tag size="large" type="warning">待复习 {{ reviews.length }}</el-tag></header>
    <section v-if="reviews.length" class="review-list"><el-card v-for="item in reviews" :key="item.id" shadow="never" class="review-card"><div class="review-icon"><el-icon :size="24"><Calendar /></el-icon></div><div class="review-main"><span>{{ item.course_name }}</span><h3>{{ item.chapter_title }}</h3><p>已复习 {{ item.review_count }} 次 · 当前间隔 {{ item.interval_days }} 天</p></div><div class="review-actions"><el-button :icon="Reading" @click="router.push(`/courses/${item.course_id}/chapters/${item.chapter_id}/review`)">查看专题</el-button><el-button type="primary" @click="begin(item)">开始复习</el-button></div></el-card></section>
    <el-empty v-else-if="!loading" description="今天没有待复习专题，继续保持学习节奏" />
    <el-dialog v-model="dialogVisible" width="680px" :close-on-click-modal="false" destroy-on-close><template #header><div><strong>{{ active?.chapter_title }} · 章节复习</strong><p>依据个人笔记和当前专题教材完成 3 道简答题。</p></div></template><div v-loading="generating" class="review-quiz"><template v-if="questions.length"><span class="quiz-progress">第 {{ currentIndex + 1 }} / {{ questions.length }} 题 · {{ questions[currentIndex].source_position }}</span><h3>{{ questions[currentIndex].question }}</h3><el-input v-model="answer" type="textarea" :rows="7" maxlength="3000" show-word-limit :disabled="!!result" placeholder="请用自己的语言作答，注意写出核心概念、观点和逻辑依据。" /><section v-if="result" class="review-feedback" :class="result.is_correct ? 'correct' : 'improve'"><strong>{{ result.is_correct ? '回答较完整' : '建议继续完善' }}</strong><p>{{ result.feedback }}</p><h4>教材依据与参考要点</h4><p>{{ result.reference_answer }}</p></section><footer><el-button v-if="!result" type="primary" @click="submit">提交作答</el-button><el-button v-else type="primary" @click="next">{{ result.completed ? '完成本次复习' : '下一题' }}</el-button></footer></template></div></el-dialog>
  </div>
</template>
