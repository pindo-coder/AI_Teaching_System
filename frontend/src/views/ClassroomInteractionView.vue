<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Connection, Finished, Histogram, QuestionFilled } from '@element-plus/icons-vue'
import { courseApi } from '@/api/courses'
import type { CourseDetail } from '@/types'
import { useAuthStore } from '@/stores/auth'
import { classroomApi, type ClassroomActivity, type DiscussionReply, type DiscussionThread } from '@/api/classroom'
import { teachingClassApi, type TeachingClass } from '@/api/teachingClasses'
import { agentApi, type LessonPublication } from '@/api/agents'
import { getErrorMessage } from '@/utils/error'
import { beijingTimestamp, formatBeijingDateTime } from '@/utils/time'

const loading = ref(true)
const auth = useAuthStore()
const activities = ref<ClassroomActivity[]>([])
const discussions = ref<DiscussionThread[]>([])
const selectedThread = ref<DiscussionThread | null>(null)
const discussionDrawerOpen = ref(false)
const threadReplies = ref<DiscussionReply[]>([])
const discussionReply = ref('')
const replyingTo = ref<DiscussionReply | null>(null)
const discussionScopeFilter = ref<'all' | 'global' | 'class'>('all')
const discussionSort = ref<'created' | 'updated'>('updated')
const discussionPage = ref(1)
const discussionPageSize = 10
const showDiscussionForm = ref(false)
const discussionPublishing = ref(false)
const discussionForm = reactive<{ teachingClassId?: number; courseId?: number; chapterId?: number; title: string; content: string }>({ title: '', content: '' })
const activeMode = ref<'classroom' | 'free'>('classroom')
const publications = ref<LessonPublication[]>([])
const responseText = ref<Record<number, string>>({})
const route = useRoute()
const textbook = ref<CourseDetail | null>(null)
const selectedChapterId = ref<number>()
const selectedCourseId = ref<number>()
const availableCourses = ref<CourseDetail[]>([])
const allCourses = ref<CourseDetail[]>([])
const teachingClasses = ref<TeachingClass[]>([])
const selectedClassId = ref<number>()
const activity = reactive({ question: '中国式现代化为什么既有各国现代化的共同特征，又有基于自己国情的中国特色？', minutes: 8 })
const firstChapter = computed(() => textbook.value?.chapters.find((item) => item.id === selectedChapterId.value) || textbook.value?.chapters[0] || null)
const discussionCourseOptions = computed(() => {
  const selected = teachingClasses.value.find((item) => item.id === discussionForm.teachingClassId)
  return selected ? allCourses.value.filter((item) => selected.material_ids.includes(item.id)) : allCourses.value
})
const discussionChapterOptions = computed(() => allCourses.value.find((item) => item.id === discussionForm.courseId)?.chapters || [])
const filteredDiscussions = computed(() => discussions.value
  .filter((item) => discussionScopeFilter.value === 'all'
    || (discussionScopeFilter.value === 'global' ? item.teaching_class_id === null : item.teaching_class_id !== null))
  .sort((left, right) => {
    if (left.is_pinned !== right.is_pinned) return Number(right.is_pinned) - Number(left.is_pinned)
    const field = discussionSort.value === 'created' ? 'created_time' : 'updated_time'
    return beijingTimestamp(right[field]) - beijingTimestamp(left[field])
  }))
const pagedDiscussions = computed(() => filteredDiscussions.value.slice(
  (discussionPage.value - 1) * discussionPageSize, discussionPage.value * discussionPageSize,
))
const visibleActivities = computed(() => activities.value.filter((item) =>
  (!selectedClassId.value || item.teaching_class_id === selectedClassId.value)
  && (!selectedCourseId.value || item.course_id === selectedCourseId.value)
  && (!selectedChapterId.value || item.chapter_id === selectedChapterId.value)))
const visiblePublications = computed(() => publications.value.filter((item) =>
  (!selectedClassId.value || item.teaching_class_id === selectedClassId.value)
  && (!selectedCourseId.value || item.course_id === selectedCourseId.value)
  && (!selectedChapterId.value || item.chapter_id === selectedChapterId.value)))
const patterns = [
  { title: '随堂问答', desc: '围绕一个核心概念生成递进式提问。', icon: QuestionFilled },
  { title: '观点辨析', desc: '给出正误判断、理由说明和追问。', icon: ChatDotRound },
  { title: '小组讨论', desc: '按主题分组，产出讨论任务和汇报要求。', icon: Connection },
  { title: '即时反馈', desc: '记录课堂表现，形成课后巩固方向。', icon: Histogram },
]

onMounted(async () => {
  try {
    teachingClasses.value = (await teachingClassApi.list()).data.data.filter((item) => item.status === 'active' || item.status === 'not_started')
    const courses = (await courseApi.list()).data.data
    allCourses.value = (await Promise.all(courses.map((item) => courseApi.detail(item.id).then((response) => response.data.data).catch(() => null)))).filter((item): item is CourseDetail => Boolean(item))
    selectedClassId.value = teachingClasses.value[0]?.id
    await loadSelectedTextbook()
    if (route.query.mode === 'free') activeMode.value = 'free'
    const newsTitle = typeof route.query.news_title === 'string' ? route.query.news_title : ''
    if (newsTitle) activity.question = `围绕时政“${newsTitle}”，联系教材专题开展课堂讨论。`
    activities.value = (await classroomApi.list()).data.data
    await loadDiscussions()
    publications.value = (await agentApi.publications()).data.data
  } finally { loading.value = false }
})

async function loadSelectedTextbook() {
  const selected = teachingClasses.value.find((item) => item.id === selectedClassId.value)
  const courseIds = selected?.material_ids?.length ? selected.material_ids : (selected?.primary_course_id ? [selected.primary_course_id] : [])
  availableCourses.value = (await Promise.all(courseIds.map((id) => courseApi.detail(id).then((response) => response.data.data).catch(() => null)))).filter((item): item is CourseDetail => Boolean(item))
  selectedCourseId.value = selected?.primary_course_id || availableCourses.value[0]?.id
  textbook.value = availableCourses.value.find((item) => item.id === selectedCourseId.value) || null
  selectedChapterId.value = textbook.value?.chapters[0]?.id
}
watch(selectedClassId, async () => { await loadSelectedTextbook(); await loadDiscussions() })
watch(selectedCourseId, () => {
  textbook.value = availableCourses.value.find((item) => item.id === selectedCourseId.value) || null
  selectedChapterId.value = textbook.value?.chapters[0]?.id
})
watch(() => discussionForm.teachingClassId, () => { discussionForm.courseId = undefined; discussionForm.chapterId = undefined })
watch(() => discussionForm.courseId, () => { discussionForm.chapterId = undefined })
watch([discussionScopeFilter, discussionSort], () => { discussionPage.value = 1 })

async function loadDiscussions() {
  discussions.value = (await classroomApi.discussions()).data.data
}

async function createDiscussion() {
  if (!discussionForm.title.trim() || !discussionForm.content.trim()) return ElMessage.warning('请填写讨论标题和内容')
  discussionPublishing.value = true
  try {
    await classroomApi.createDiscussion({ teaching_class_id: discussionForm.teachingClassId, course_id: discussionForm.courseId, chapter_id: discussionForm.chapterId, title: discussionForm.title.trim(), content: discussionForm.content.trim() })
    discussionForm.teachingClassId = undefined; discussionForm.courseId = undefined; discussionForm.chapterId = undefined; discussionForm.title = ''; discussionForm.content = ''; showDiscussionForm.value = false
    await loadDiscussions()
    ElMessage.success('讨论已发布')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '讨论发布失败，请稍后重试'))
  } finally {
    discussionPublishing.value = false
  }
}

function discussionScopeLabel(item: DiscussionThread) {
  const className = item.teaching_class_id ? teachingClasses.value.find((value) => value.id === item.teaching_class_id)?.name : '全体讨论'
  const course = item.course_id ? allCourses.value.find((value) => value.id === item.course_id) : null
  const chapter = course?.chapters.find((value) => value.id === item.chapter_id)
  return [className || '指定教学班', course?.name, chapter?.title].filter(Boolean).join(' · ')
}

async function openDiscussion(item: DiscussionThread) {
  selectedThread.value = item
  discussionDrawerOpen.value = true
  threadReplies.value = (await classroomApi.discussionReplies(item.id)).data.data
}

async function replyToDiscussion() {
  if (!selectedThread.value || !discussionReply.value.trim()) return ElMessage.warning('请填写回贴内容')
  try {
    await classroomApi.replyDiscussion(selectedThread.value.id, discussionReply.value.trim(), replyingTo.value?.id)
    discussionReply.value = ''; replyingTo.value = null
    await loadDiscussions(); await openDiscussion(selectedThread.value)
    ElMessage.success('回贴成功')
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '回贴失败')) }
}

function parentReplyAuthor(reply: DiscussionReply) {
  if (!reply.parent_reply_id) return ''
  return threadReplies.value.find((item) => item.id === reply.parent_reply_id)?.author.name || '已删除用户'
}

function canModerate(item: DiscussionThread) {
  return auth.isAdmin || (auth.user?.role === 'teacher' && item.teaching_class_id !== null
    && teachingClasses.value.some((value) => value.id === item.teaching_class_id))
}

async function editThread(item: DiscussionThread) {
  try {
    const title = await ElMessageBox.prompt('修改讨论标题', '编辑讨论', { inputValue: item.title, inputValidator: (value) => Boolean(value.trim()) || '标题不能为空' })
    const content = await ElMessageBox.prompt('修改讨论内容', '编辑讨论', { inputValue: item.content, inputType: 'textarea', inputValidator: (value) => Boolean(value.trim()) || '内容不能为空' })
    const updated = (await classroomApi.updateDiscussion(item.id, { title: title.value.trim(), content: content.value.trim() })).data.data
    selectedThread.value = updated; await loadDiscussions(); ElMessage.success('讨论已更新')
  } catch (error: unknown) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '讨论更新失败'))
  }
}

async function deleteThread(item: DiscussionThread) {
  try {
    await ElMessageBox.confirm('删除后该讨论将不再显示，是否继续？', '删除讨论', { type: 'warning' })
    await classroomApi.deleteDiscussion(item.id); discussionDrawerOpen.value = false
    await loadDiscussions(); ElMessage.success('讨论已删除')
  } catch (error: unknown) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '讨论删除失败'))
  }
}

async function editReply(reply: DiscussionReply) {
  try {
    const result = await ElMessageBox.prompt('修改回贴内容', '编辑回贴', { inputValue: reply.content, inputType: 'textarea', inputValidator: (value) => Boolean(value.trim()) || '内容不能为空' })
    await classroomApi.updateReply(reply.id, result.value.trim())
    if (selectedThread.value) await openDiscussion(selectedThread.value)
    ElMessage.success('回贴已更新')
  } catch (error: unknown) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '回贴更新失败'))
  }
}

async function deleteReply(reply: DiscussionReply) {
  try {
    await ElMessageBox.confirm('确认删除这条回贴？', '删除回贴', { type: 'warning' })
    await classroomApi.deleteReply(reply.id)
    if (selectedThread.value) await openDiscussion(selectedThread.value)
    ElMessage.success('回贴已删除')
  } catch (error: unknown) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '回贴删除失败'))
  }
}

async function togglePin(item: DiscussionThread) {
  try { await classroomApi.pinDiscussion(item.id); await loadDiscussions() }
  catch (error: unknown) { ElMessage.error(getErrorMessage(error, '置顶操作失败')) }
}

async function toggleClose(item: DiscussionThread) {
  try {
    const updated = (await classroomApi.closeDiscussion(item.id)).data.data
    await loadDiscussions()
    if (selectedThread.value?.id === item.id) await openDiscussion(updated)
  } catch (error: unknown) { ElMessage.error(getErrorMessage(error, '讨论状态更新失败')) }
}

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

async function downloadPublishedPpt(item: LessonPublication) {
  const response = await agentApi.downloadPublicationPpt(item.id)
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = item.ppt_file_name || `${item.title}.pptx`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-header">
      <div>
        <p class="eyebrow">课堂互动</p>
        <h1>{{ activeMode === 'classroom' ? '把专题学习变成可参与的课堂活动' : '在师生交流中共同深化理解' }}</h1>
        <p>{{ activeMode === 'classroom' ? '教师发布课堂任务，学生围绕当前教材专题提交观点。' : '学生和教师都可以发起主题、发表回贴，自由讨论与课堂任务相互独立。' }}</p>
      </div>
    </header>

    <nav class="mode-tabs" aria-label="讨论模式切换">
      <div class="mode-tab-list">
        <button type="button" class="mode-tab" :class="{ active: activeMode === 'classroom' }" @click="activeMode = 'classroom'">
          <span>课堂讨论</span><small>{{ visibleActivities.length }} 项活动</small>
        </button>
        <button type="button" class="mode-tab" :class="{ active: activeMode === 'free' }" @click="activeMode = 'free'">
          <span>自由讨论</span><small>{{ discussions.length }} 个主题</small>
        </button>
      </div>
      <el-button v-if="activeMode === 'free'" type="primary" @click="showDiscussionForm = !showDiscussionForm">{{ showDiscussionForm ? '取消发帖' : '发起讨论' }}</el-button>
    </nav>

    <section class="interaction-layout interaction-layout-single">
      <div v-if="activeMode === 'classroom'">
        <el-card shadow="never" class="published-lessons">
          <template #header>
            <div class="content-heading">
              <span>教师发布的课程成果</span>
              <el-tag type="success">{{ visiblePublications.length }} 项</el-tag>
            </div>
          </template>
          <div v-if="visiblePublications.length" class="lesson-publication-list">
            <article v-for="item in visiblePublications" :key="item.id" class="lesson-publication">
              <div>
                <small>{{ item.chapter_title }} · {{ item.teacher_name }}</small>
                <h3>{{ item.title }}</h3>
                <p>{{ item.description || '教师已发布本专题教学成果。' }}</p>
              </div>
              <el-button
                v-if="item.ppt_available"
                type="primary"
                plain
                @click="downloadPublishedPpt(item)"
              >
                下载教学 PPT
              </el-button>
            </article>
          </div>
          <el-empty v-else description="当前教学班尚未发布课程成果" :image-size="80" />
        </el-card>

        <section v-if="activeMode === 'classroom'" class="module-grid interaction-patterns">
          <el-card v-for="item in patterns" :key="item.title" shadow="never" class="module-card quiet-card">
            <el-icon :size="24"><component :is="item.icon" /></el-icon>
            <h3>{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
          </el-card>
        </section>

        <el-card v-if="activeMode === 'classroom' && auth.isTeacher" shadow="never" class="interaction-builder">
          <template #header><div class="content-heading"><span>互动任务生成</span><el-tag type="success">MVP</el-tag></div></template>
          <el-form label-position="top">
            <div class="scope-fields">
              <el-form-item label="所属教学班"><el-select v-model="selectedClassId" placeholder="请选择教学班"><el-option v-for="item in teachingClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" /></el-select></el-form-item>
              <el-form-item label="关联教材"><el-select v-model="selectedCourseId" placeholder="请选择教材"><el-option v-for="item in availableCourses" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
              <el-form-item label="关联专题"><el-select v-model="selectedChapterId" placeholder="请选择专题"><el-option v-for="chapter in textbook?.chapters" :key="chapter.id" :label="chapter.title" :value="chapter.id" /></el-select></el-form-item>
            </div>
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
        <el-card v-else-if="activeMode === 'classroom'" shadow="never" class="interaction-builder student-interaction-hint"><el-result icon="info" title="学生参与区" sub-title="教师发布课堂互动后，你可以在右侧选择活动并提交自己的观点。" /></el-card>
      </div>
      <div :class="{ 'full-mode-column': activeMode === 'free' }">
        <el-card v-if="activeMode === 'classroom'" shadow="never" class="interaction-activities"><template #header><div class="content-heading"><span>已发布的课堂互动</span><el-tag>{{ visibleActivities.length }} 项</el-tag></div></template><div v-if="visibleActivities.length" class="published-activities"><article v-for="item in visibleActivities" :key="item.id" class="published-activity"><span class="activity-label">{{ item.minutes }} 分钟讨论</span><h3>{{ item.question }}</h3><p v-if="auth.isTeacher" class="muted">教师可继续组织课堂讨论，学生将提交观点。</p><template v-else><el-input v-model="responseText[item.id]" type="textarea" :rows="3" placeholder="写下你的观点或问题……" /><el-button type="primary" size="small" @click="submitResponse(item)">提交观点</el-button></template></article></div><el-empty v-else description="当前教学班尚未发布互动" /></el-card>
        <el-card v-if="activeMode === 'free'" shadow="never" class="discussion-board">
          <template #header><div class="content-heading"><span>自由讨论区</span><el-tag>{{ discussions.length }} 个主题</el-tag></div></template>
          <p class="discussion-hint">这里是师生自由交流区，与课堂互动任务相互独立。</p>
          <el-form v-if="showDiscussionForm" class="discussion-form" label-position="top">
            <div class="scope-fields optional-scope-fields">
              <el-form-item label="讨论范围（可选）"><el-select v-model="discussionForm.teachingClassId" clearable placeholder="不选择则面向全体"><el-option v-for="item in teachingClasses" :key="item.id" :label="`${item.name} · ${item.term_name}`" :value="item.id" /></el-select></el-form-item>
              <el-form-item label="关联课程（可选）"><el-select v-model="discussionForm.courseId" clearable placeholder="不关联课程"><el-option v-for="item in discussionCourseOptions" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
              <el-form-item label="关联专题（可选）"><el-select v-model="discussionForm.chapterId" clearable :disabled="!discussionForm.courseId" placeholder="不关联专题"><el-option v-for="chapter in discussionChapterOptions" :key="chapter.id" :label="chapter.title" :value="chapter.id" /></el-select></el-form-item>
            </div>
            <el-alert class="scope-tip" :title="discussionForm.teachingClassId ? '仅所选教学班成员可查看和参与' : '当前将发布为全体讨论，所有登录用户均可查看和参与'" type="info" :closable="false" show-icon />
            <el-form-item label="讨论标题"><el-input v-model="discussionForm.title" maxlength="200" show-word-limit placeholder="写一个清晰的讨论标题" /></el-form-item>
            <el-form-item label="讨论内容"><el-input v-model="discussionForm.content" type="textarea" :rows="4" maxlength="10000" show-word-limit placeholder="分享问题、观点或学习案例" /></el-form-item>
            <el-button type="primary" :icon="Finished" :loading="discussionPublishing" @click="createDiscussion">发布讨论</el-button>
          </el-form>
          <div class="discussion-toolbar">
            <el-radio-group v-model="discussionScopeFilter" size="small"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="global">全体讨论</el-radio-button><el-radio-button value="class">我的教学班</el-radio-button></el-radio-group>
            <el-select v-model="discussionSort" size="small" class="discussion-sort"><el-option label="最新回复" value="updated" /><el-option label="最新发布" value="created" /></el-select>
          </div>
          <div v-if="filteredDiscussions.length" class="discussion-list">
            <article v-for="item in pagedDiscussions" :key="item.id" class="discussion-item" :class="{ pinned: item.is_pinned }" @click="openDiscussion(item)">
              <div class="discussion-item-main"><div class="discussion-labels"><span v-if="item.is_pinned" class="activity-label">置顶</span><el-tag v-if="item.status === 'closed'" size="small" type="info">已关闭</el-tag><el-tag size="small" effect="plain">{{ discussionScopeLabel(item) }}</el-tag></div><h3>{{ item.title }}</h3><p>{{ item.content }}</p><small>{{ item.author.name }} · {{ item.author.role === 'teacher' ? '教师' : '学生' }} · 发布于 {{ formatBeijingDateTime(item.created_time) }} · {{ item.reply_count }} 条回贴</small></div>
              <div v-if="canModerate(item)" class="discussion-actions" @click.stop><el-button text size="small" @click="togglePin(item)">{{ item.is_pinned ? '取消置顶' : '置顶' }}</el-button><el-button text size="small" @click="toggleClose(item)">{{ item.status === 'closed' ? '重新开放' : '关闭' }}</el-button></div>
            </article>
          </div><el-empty v-else description="当前范围还没有自由讨论" />
          <el-pagination v-if="filteredDiscussions.length > discussionPageSize" v-model:current-page="discussionPage" class="discussion-pagination" layout="prev, pager, next" :page-size="discussionPageSize" :total="filteredDiscussions.length" />
        </el-card>
      </div>
    </section>
    <el-drawer v-model="discussionDrawerOpen" title="自由讨论详情" size="min(560px, 100%)" :destroy-on-close="false">
      <template v-if="selectedThread">
        <div class="thread-heading"><div><h2 class="thread-title">{{ selectedThread.title }}</h2><p class="thread-meta">{{ selectedThread.author.name }} · {{ selectedThread.author.role === 'teacher' ? '教师' : '学生' }} · 发布于 {{ formatBeijingDateTime(selectedThread.created_time) }}</p></div><div v-if="selectedThread.author.id === auth.user?.id || canModerate(selectedThread)"><el-button v-if="selectedThread.author.id === auth.user?.id" text size="small" @click="editThread(selectedThread)">编辑</el-button><el-button text size="small" type="danger" @click="deleteThread(selectedThread)">删除</el-button></div></div><p class="thread-content">{{ selectedThread.content }}</p>
        <el-divider content-position="left">回贴 {{ threadReplies.length }}</el-divider>
        <div class="reply-list"><div v-for="reply in threadReplies" :key="reply.id" class="reply-item" :class="{ deleted: reply.status === 'deleted' }"><div class="reply-heading"><div><strong>{{ reply.author.name }} <el-tag v-if="reply.author.role === 'teacher'" size="small" type="warning">教师</el-tag></strong><small class="reply-time">{{ formatBeijingDateTime(reply.created_time) }}</small></div><div v-if="reply.status === 'published'"><el-button text size="small" @click="replyingTo = reply">回复</el-button><el-button v-if="reply.author.id === auth.user?.id" text size="small" @click="editReply(reply)">编辑</el-button><el-button v-if="reply.author.id === auth.user?.id || canModerate(selectedThread)" text size="small" type="danger" @click="deleteReply(reply)">删除</el-button></div></div><small v-if="reply.parent_reply_id" class="reply-target">回复 @{{ parentReplyAuthor(reply) }}</small><p>{{ reply.content }}</p></div><el-empty v-if="!threadReplies.length" description="还没有回贴" :image-size="60" /></div>
        <div v-if="selectedThread.status !== 'closed'"><div v-if="replyingTo" class="replying-tip">正在回复 @{{ replyingTo.author.name }} <el-button text size="small" @click="replyingTo = null">取消</el-button></div><el-input v-model="discussionReply" type="textarea" :rows="4" maxlength="5000" show-word-limit :placeholder="replyingTo ? `回复 ${replyingTo.author.name}` : '写下你的回贴'" /><el-button type="primary" class="reply-submit" @click="replyToDiscussion">发表回贴</el-button></div><el-alert v-else title="该讨论已关闭，暂不能继续回贴" type="info" :closable="false" />
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.mode-tabs { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; min-height: 62px; padding: 0 8px; margin-bottom: 18px; border-bottom: 1px solid var(--line); }
.mode-tab-list { display: flex; align-self: stretch; gap: 8px; }
.mode-tab { position: relative; display: flex; align-items: center; gap: 9px; padding: 0 18px; color: var(--ink-500); background: transparent; border: 0; cursor: pointer; font: inherit; }
.mode-tab::after { position: absolute; right: 12px; bottom: -1px; left: 12px; height: 3px; background: transparent; border-radius: 3px 3px 0 0; content: ''; }
.mode-tab span { font-size: 17px; font-weight: 700; }
.mode-tab small { padding: 3px 7px; color: var(--ink-500); background: var(--surface-soft); border-radius: 999px; }
.mode-tab:hover, .mode-tab.active { color: var(--action-blue); }
.mode-tab.active::after { background: var(--action-blue); }
.mode-tab.active small { color: var(--action-blue); background: #eef5fb; }
.scope-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.scope-fields :deep(.el-select) { width: 100%; }
.scope-tip { margin-bottom: 18px; }
.discussion-labels { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.full-mode-column { grid-column: 1 / -1; }
.published-lessons { margin-bottom: 20px; }
.discussion-board { margin-top: 0; }
.discussion-heading-actions { display: flex; align-items: center; gap: 10px; }
.discussion-hint { color: var(--ink-500); margin-top: 0; }
.discussion-form { padding: 16px; margin-bottom: 16px; background: var(--surface-soft); border: 1px solid var(--line); }
.discussion-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.discussion-sort { width: 130px; }
.discussion-list { display: grid; gap: 10px; }
.discussion-item { display: flex; justify-content: space-between; gap: 16px; padding: 16px; border: 1px solid var(--line); cursor: pointer; transition: border-color .2s; }
.discussion-item:hover, .discussion-item.pinned { border-color: var(--action-blue); }
.discussion-item h3, .discussion-item p { margin: 0 0 7px; }
.discussion-item p { color: var(--ink-500); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.discussion-item small, .thread-meta { color: var(--ink-500); }
.discussion-actions { flex: 0 0 auto; }
.discussion-pagination { justify-content: center; margin-top: 18px; }
.thread-heading, .reply-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.thread-title { margin: 0; }
.thread-content { white-space: pre-wrap; line-height: 1.7; }
.reply-list { display: grid; gap: 12px; margin-bottom: 18px; }
.reply-item { padding: 12px; background: var(--surface-soft); border-left: 3px solid var(--action-blue); }
.reply-item.deleted { opacity: .7; border-left-color: var(--line); }
.reply-item p { margin: 8px 0 0; white-space: pre-wrap; }
.reply-target { display: block; margin-top: 6px; color: var(--action-blue); }
.reply-time { display: block; margin-top: 4px; color: var(--ink-500); }
.replying-tip { display: flex; align-items: center; justify-content: space-between; padding: 7px 10px; margin-bottom: 8px; color: var(--action-blue); background: #eef5fb; border-radius: var(--radius-input); }
.reply-submit { margin-top: 10px; }
.lesson-publication-list { display: grid; gap: 12px; }
.lesson-publication { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 18px; background: linear-gradient(130deg, #f7faff, #fff9f1); border: 1px solid var(--line); border-left: 4px solid var(--authority-red); border-radius: var(--radius-card); }
.lesson-publication h3, .lesson-publication p { margin: 0; }
.lesson-publication h3 { margin: 4px 0 8px; }
.lesson-publication small { color: var(--action-blue); font-weight: 700; }
.lesson-publication p { color: var(--ink-500); line-height: 1.6; }
@media (max-width: 767px) {
  .mode-tabs { align-items: stretch; flex-direction: column; padding: 0 0 12px; }
  .mode-tab-list { width: 100%; }
  .mode-tab { flex: 1; justify-content: center; padding: 14px 8px; }
  .mode-tabs :deep(.el-button) { width: 100%; }
  .discussion-toolbar { align-items: stretch; flex-direction: column; }
  .discussion-sort { width: 100%; }
  .scope-fields { grid-template-columns: 1fr; gap: 0; }
  .lesson-publication { align-items: flex-start; flex-direction: column; }
  .lesson-publication :deep(.el-button) { width: 100%; }
}
</style>
