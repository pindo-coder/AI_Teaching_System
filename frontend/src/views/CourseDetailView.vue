<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { courseApi } from '@/api/courses'
import { useAuthStore } from '@/stores/auth'
import type { CourseDetail, LearningStage } from '@/types'
import { textbookPreview } from '@/utils/textbookText'
import KnowledgeGraph from '@/components/KnowledgeGraph.vue'

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
  await router.push(`/courses/${courseId.value}/chapters/${chapterId}/${stage}`)
}
async function deleteCourse() {
  const confirmed = await ElMessageBox.confirm(
    `删除“${course.value?.name || '这本教材'}”后，相关专题、学习记录和知识库资料也将一并删除，是否继续？`,
    '删除教材',
    { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  await courseApi.remove(courseId.value)
  ElMessage.success('教材已删除')
  await router.push('/courses')
}
onMounted(loadCourse)
</script>

<template>
  <div v-loading="loading">
    <div class="course-breadcrumb"><el-button link @click="$router.push('/courses')">课程中心</el-button><span>/</span><span>{{ course?.name || '教材详情' }}</span></div>
    <header class="course-hero course-detail-hero"><div class="course-hero-copy"><p class="eyebrow">高校思政课 · 教材空间</p><h1>{{ course?.name }}</h1><div class="course-meta"><span>专题 {{ course?.chapters.length || 0 }}</span><span>学习阶段 3 个</span><span>AI 辅助学习</span></div><div class="course-intro-card"><div class="intro-heading"><strong>课程介绍</strong><span>围绕教材专题开展学习</span></div><p>{{ course?.description || '围绕教材内容，结合预习、课后巩固和考前冲刺，形成连续的学习辅助。' }}</p></div></div><div class="course-hero-visual"><div class="hero-orbit"></div><div class="hero-metric metric-top"><strong>{{ course?.chapters.length || 0 }}</strong><span>教材专题</span></div><div class="hero-metric metric-left"><strong>3</strong><span>学习阶段</span></div><div class="hero-metric metric-right"><strong>AI</strong><span>学习辅助</span></div><div class="hero-core">思政<br>AI</div></div><div v-if="auth.isAdmin" class="hero-admin-actions"><el-button class="hero-admin-button" type="warning" @click="dialogVisible = true">添加专题</el-button><el-button class="hero-admin-button hero-delete-button" type="danger" plain @click="deleteCourse">删除教材</el-button></div></header>
    <nav class="course-tabs" aria-label="教材内容导航"><a href="#overview">内容概览</a><a href="#chapters">专题章节</a><a href="#learning-path">学习路径</a></nav>
    <section class="course-tools"><el-card shadow="hover" class="course-tool-card" @click="router.push('/current-affairs')"><span class="tool-kicker">关联教材</span><h3>时政要点</h3><p>从现实议题回到教材知识，查看当前时政学习内容。</p><el-link type="primary" :underline="false">进入时政要点 →</el-link></el-card><el-card shadow="hover" class="course-tool-card" @click="router.push('/interaction')"><span class="tool-kicker">课堂场景</span><h3>课堂互动</h3><p>围绕当前教材专题生成讨论题、随堂问答和观点辨析。</p><el-link type="primary" :underline="false">进入课堂互动 →</el-link></el-card></section>
    <KnowledgeGraph v-if="course" id="overview" :course-name="course.name" :chapters="course.chapters" @learn="(chapterId) => startLearning(chapterId, 'preview')" />
    <div class="course-detail-layout">
      <main>
        <div class="section-heading course-section-heading"><div><p class="eyebrow">专题目录</p><h2>按教材内容开展学习</h2></div><span class="muted">选择专题开始学习</span></div>
        <section id="chapters" class="chapter-list">
          <el-card v-for="chapter in course?.chapters" :key="chapter.id" shadow="never" class="chapter-card">
            <div class="chapter-number">{{ String(chapter.sort_order || chapter.id).padStart(2, '0') }}</div>
            <div class="chapter-main"><div class="chapter-label">专题 {{ String(chapter.sort_order || chapter.id).padStart(2, '0') }}</div><h3>{{ chapter.title }}</h3><p class="chapter-content-preview">{{ textbookPreview(chapter.content) || '本专题内容待完善' }}</p></div>
            <div class="chapter-actions"><el-button size="small" @click="startLearning(chapter.id, 'preview')">预习</el-button><el-button size="small" @click="startLearning(chapter.id, 'review')">巩固</el-button><el-button size="small" @click="startLearning(chapter.id, 'exam')">冲刺</el-button></div>
          </el-card>
          <el-empty v-if="course && !course.chapters.length" description="当前教材暂未添加专题" />
        </section>
      </main>
      <aside id="learning-path" class="course-side-column">
        <el-card shadow="never" class="course-side-card"><p class="eyebrow">学习路径</p><h3>循序渐进掌握教材</h3><div class="path-item"><span class="path-index">1</span><div><strong>预习空间</strong><p>先了解专题内容，形成问题意识。</p></div></div><div class="path-item"><span class="path-index">2</span><div><strong>课后巩固</strong><p>梳理知识结构，完成学习总结。</p></div></div><div class="path-item"><span class="path-index">3</span><div><strong>考前冲刺</strong><p>通过模拟问题检验掌握情况。</p></div></div></el-card>
        <el-card shadow="never" class="course-side-card course-note-card"><p class="eyebrow">学习提示</p><p>进入任一专题后，可在当前页面使用 AI 辅助完成总结、复习提纲和模拟题。</p></el-card>
      </aside>
    </div>
    <el-dialog v-model="dialogVisible" title="添加专题" width="560px"><el-form label-position="top"><el-form-item label="专题标题" required><el-input v-model="form.title" /></el-form-item><el-form-item label="专题内容"><el-input v-model="form.content" type="textarea" :rows="5" /></el-form-item><el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" /></el-form-item></el-form><template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="createChapter">保存</el-button></template></el-dialog>
  </div>
</template>
