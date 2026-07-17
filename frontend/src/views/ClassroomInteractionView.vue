<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Connection, Finished, Histogram, QuestionFilled } from '@element-plus/icons-vue'
import { courseApi } from '@/api/courses'
import type { CourseDetail } from '@/types'
import { useAuthStore } from '@/stores/auth'
import { classroomApi, type ClassroomActivity } from '@/api/classroom'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'

const loading = ref(true)
const auth = useAuthStore()
const activities = ref<ClassroomActivity[]>([])
const responseText = ref<Record<number, string>>({})
const route = useRoute()
const textbook = ref<CourseDetail | null>(null)
const selectedChapterId = ref<number>()
const teachingClasses = ref<TeachingClass[]>([])
const selectedClassId = ref<number>()
const activity = reactive({ question: '中国式现代化为什么既有各国现代化的共同特征，又有基于自己国情的中国特色？', minutes: 8 })
const firstChapter = computed(() => textbook.value?.chapters.find((item) => item.id === selectedChapterId.value) || textbook.value?.chapters[0] || null)
const visibleActivities = computed(() => selectedClassId.value ? activities.value.filter((item) => item.teaching_class_id === selectedClassId.value) : activities.value)
const patterns = [
  { title: '随堂问答', desc: '围绕一个核心概念生成递进式提问。', icon: QuestionFilled },
  { title: '观点辨析', desc: '给出正误判断、理由说明和追问。', icon: ChatDotRound },
  { title: '小组讨论', desc: '按主题分组，产出讨论任务和汇报要求。', icon: Connection },
  { title: '即时反馈', desc: '记录课堂表现，形成课后巩固方向。', icon: Histogram },
]

onMounted(async () => {
  try {
    teachingClasses.value = (await teachingClassApi.list()).data.data.filter((item) => item.status === 'active' || item.status === 'not_started')
    selectedClassId.value = teachingClasses.value[0]?.id
    await loadSelectedTextbook()
    const newsTitle = typeof route.query.news_title === 'string' ? route.query.news_title : ''
    if (newsTitle) activity.question = `围绕时政“${newsTitle}”，联系教材专题开展课堂讨论。`
    activities.value = (await classroomApi.list()).data.data
  } finally { loading.value = false }
})

async function loadSelectedTextbook() {
  const selected = teachingClasses.value.find((item) => item.id === selectedClassId.value)
  textbook.value = selected?.primary_course_id ? (await courseApi.detail(selected.primary_course_id)).data.data : null
  selectedChapterId.value = textbook.value?.chapters[0]?.id
}
watch(selectedClassId, () => void loadSelectedTextbook())

async function launchActivity() {
  if (!activity.question.trim()) return ElMessage.warning('请输入互动主题')
  if (!auth.isTeacher) return ElMessage.warning('只有教师可以发布课堂互动')
  if (!selectedClassId.value || !textbook.value || !firstChapter.value) return ElMessage.warning('请先选择教学班及教材专题')
  await classroomApi.publish({ teaching_class_id: selectedClassId.value, course_id: textbook.value.id, chapter_id: firstChapter.value.id, question: activity.question.trim(), minutes: activity.minutes })
  activities.value = (await classroomApi.list()).data.data
  ElMessage.success('课堂互动已发布，学生可以参与')
}
async function submitResponse(item: ClassroomActivity) {
  const answer = responseText.value[item.id]?.trim()
  if (!answer) return ElMessage.warning('请先填写你的观点')
  await classroomApi.respond(item.id, answer)
  responseText.value[item.id] = ''
  ElMessage.success('观点提交成功')
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

        <el-card v-if="auth.isTeacher" shadow="never" class="interaction-builder">
          <template #header><div class="content-heading"><span>互动任务生成</span><el-tag type="success">MVP</el-tag></div></template>
          <el-form label-position="top">
            <el-form-item label="所属教学班">
              <el-select v-model="selectedClassId" placeholder="请选择教学班"><el-option v-for="item in teachingClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" /></el-select>
            </el-form-item>
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
          <el-button v-if="auth.isTeacher" type="primary" :icon="Finished" @click="launchActivity">发布课堂活动</el-button>
          <div class="activity-preview">
            <strong>活动预览</strong>
            <p>围绕“{{ activity.question }}”进行 {{ activity.minutes }} 分钟讨论：先独立思考，再小组交流，最后由教师引导回到教材专题“{{ firstChapter?.title || '未选择专题' }}”。</p>
          </div>
        </el-card>
        <el-card v-else shadow="never" class="interaction-builder student-interaction-hint"><el-result icon="info" title="学生参与区" sub-title="教师发布课堂互动后，你可以在右侧选择活动并提交自己的观点。" /></el-card>
      </div>
      <el-card shadow="never" class="interaction-activities"><template #header><div class="content-heading"><span>已发布的课堂互动</span><el-tag>{{ visibleActivities.length }} 项</el-tag></div></template><div v-if="visibleActivities.length" class="published-activities"><article v-for="item in visibleActivities" :key="item.id" class="published-activity"><span class="activity-label">{{ item.minutes }} 分钟讨论</span><h3>{{ item.question }}</h3><p v-if="auth.isTeacher" class="muted">教师可继续组织课堂讨论，学生将提交观点。</p><template v-else><el-input v-model="responseText[item.id]" type="textarea" :rows="3" placeholder="写下你的观点或问题……" /><el-button type="primary" size="small" @click="submitResponse(item)">提交观点</el-button></template></article></div><el-empty v-else description="当前教学班尚未发布互动" /></el-card>
    </section>
  </div>
</template>
