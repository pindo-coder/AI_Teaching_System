<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Calendar, CircleCheck, Reading } from '@element-plus/icons-vue'
import { studyApi, type ReviewItem } from '@/api/study'

const router = useRouter()
const loading = ref(true)
const reviews = ref<ReviewItem[]>([])

async function load() {
  loading.value = true
  try { reviews.value = (await studyApi.reviews()).data.data } finally { loading.value = false }
}
async function complete(item: ReviewItem) {
  const result = (await studyApi.completeReview(item.chapter_id)).data.data
  ElMessage.success(`复习完成，${result.interval_days} 天后再次提醒`)
  await load()
}
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <header class="page-header"><div><p class="eyebrow">Spaced Review</p><h1>今日复习</h1><p>按照 1、2、4、7、15、30 天间隔巩固已经学习的教材专题。</p></div><el-tag size="large" type="warning">待复习 {{ reviews.length }}</el-tag></header>
    <section v-if="reviews.length" class="review-list"><el-card v-for="item in reviews" :key="item.id" shadow="never" class="review-card"><div class="review-icon"><el-icon :size="24"><Calendar /></el-icon></div><div class="review-main"><span>{{ item.course_name }}</span><h3>{{ item.chapter_title }}</h3><p>已复习 {{ item.review_count }} 次 · 当前间隔 {{ item.interval_days }} 天</p></div><div class="review-actions"><el-button :icon="Reading" @click="router.push(`/courses/${item.course_id}/chapters/${item.chapter_id}/review`)">进入巩固</el-button><el-button type="success" :icon="CircleCheck" @click="complete(item)">完成复习</el-button></div></el-card></section>
    <el-empty v-else-if="!loading" description="今天没有待复习专题，继续保持学习节奏" />
  </div>
</template>
