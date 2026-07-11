<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { courseApi } from '@/api/courses'
import { useAuthStore } from '@/stores/auth'
import type { Course } from '@/types'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(false)
const courses = ref<Course[]>([])
const dialogVisible = ref(false)
const submitting = ref(false)
const form = reactive({ name: '', description: '' })

async function loadCourses() {
  loading.value = true
  try { courses.value = (await courseApi.list()).data.data } finally { loading.value = false }
}
async function createCourse() {
  if (!form.name.trim()) return ElMessage.warning('请输入课程名称')
  submitting.value = true
  try {
    await courseApi.create(form)
    ElMessage.success('课程创建成功')
    dialogVisible.value = false
    form.name = ''; form.description = ''
    await loadCourses()
  } finally { submitting.value = false }
}
onMounted(loadCourses)
</script>

<template>
  <div>
    <header class="page-header"><div><p class="eyebrow">课程中心</p><h1>课程与章节</h1><p>选择课程，按照章节开展预习、巩固与冲刺。</p></div><el-button v-if="auth.isAdmin" type="primary" @click="dialogVisible = true">新建课程</el-button></header>
    <div v-loading="loading" class="course-grid">
      <el-card v-for="course in courses" :key="course.id" shadow="hover" class="course-card" @click="router.push(`/courses/${course.id}`)">
        <div class="course-index">课程 {{ String(course.id).padStart(2, '0') }}</div><h2>{{ course.name }}</h2><p>{{ course.description || '暂无课程简介' }}</p><el-link type="primary" underline="never">查看课程 →</el-link>
      </el-card>
      <el-empty v-if="!loading && !courses.length" description="暂无课程，请联系管理员创建" />
    </div>
    <el-dialog v-model="dialogVisible" title="新建课程" width="520px">
      <el-form label-position="top"><el-form-item label="课程名称" required><el-input v-model="form.name" maxlength="100" /></el-form-item><el-form-item label="课程简介"><el-input v-model="form.description" type="textarea" :rows="4" /></el-form-item></el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="createCourse">创建</el-button></template>
    </el-dialog>
  </div>
</template>
