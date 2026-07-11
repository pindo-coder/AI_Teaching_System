<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { courseApi } from '@/api/courses'
import { learningApi } from '@/api/learning'
import { useAuthStore } from '@/stores/auth'
import type { CourseDetail, LearningStage } from '@/types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const courseId = computed(() => Number(route.params.id))
const course = ref<CourseDetail | null>(null)
const loading = ref(false)
const dialogVisible = ref(false)
const form = reactive({ title: '', content: '', sort_order: 0 })

async function loadCourse() {
  loading.value = true
  try { course.value = (await courseApi.detail(courseId.value)).data.data } finally { loading.value = false }
}
async function createChapter() {
  if (!form.title.trim()) return ElMessage.warning('请输入章节标题')
  await courseApi.createChapter(courseId.value, form)
  ElMessage.success('章节创建成功'); dialogVisible.value = false
  form.title = ''; form.content = ''; form.sort_order = 0
  await loadCourse()
}
async function startLearning(chapterId: number, stage: LearningStage) {
  await learningApi.updateProgress({ course_id: courseId.value, chapter_id: chapterId, learning_stage: stage, progress: 10 })
  await router.push(`/courses/${courseId.value}/chapters/${chapterId}/${stage}`)
}
onMounted(loadCourse)
</script>

<template>
  <div v-loading="loading">
    <el-button link @click="$router.push('/courses')">← 返回课程中心</el-button>
    <header class="course-hero"><div><p class="eyebrow">课程详情</p><h1>{{ course?.name }}</h1><p>{{ course?.description || '暂无课程简介' }}</p></div><el-button v-if="auth.isAdmin" type="primary" @click="dialogVisible = true">添加章节</el-button></header>
    <div class="section-heading"><div><p class="eyebrow">章节目录</p><h2>按章节开展学习</h2></div></div>
    <section class="chapter-list">
      <el-card v-for="chapter in course?.chapters" :key="chapter.id" shadow="never" class="chapter-card">
        <div class="chapter-number">{{ String(chapter.sort_order || chapter.id).padStart(2, '0') }}</div>
        <div class="chapter-main"><h3>{{ chapter.title }}</h3><p>{{ chapter.content || '本章内容待完善' }}</p></div>
        <div class="chapter-actions"><el-button size="small" @click="startLearning(chapter.id, 'preview')">预习</el-button><el-button size="small" @click="startLearning(chapter.id, 'review')">巩固</el-button><el-button size="small" @click="startLearning(chapter.id, 'exam')">冲刺</el-button></div>
      </el-card>
      <el-empty v-if="course && !course.chapters.length" description="课程暂未添加章节" />
    </section>
    <el-dialog v-model="dialogVisible" title="添加章节" width="560px"><el-form label-position="top"><el-form-item label="章节标题" required><el-input v-model="form.title" /></el-form-item><el-form-item label="章节内容"><el-input v-model="form.content" type="textarea" :rows="5" /></el-form-item><el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" /></el-form-item></el-form><template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="createChapter">保存</el-button></template></el-dialog>
  </div>
</template>
