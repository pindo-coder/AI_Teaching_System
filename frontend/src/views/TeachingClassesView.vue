<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Plus, Refresh, School, UploadFilled, UserFilled } from '@element-plus/icons-vue'
import { teachingClassApi, type AcademicTerm, type AvailableTeacher, type ClassGroup, type ClassMember, type ClassRequest, type CourseSubject, type TeachingClass } from '@/api/teachingClasses'
import { authApi } from '@/api/auth'
import { courseApi } from '@/api/courses'
import { useAuthStore } from '@/stores/auth'
import type { Course, User } from '@/types'
import { getErrorMessage } from '@/utils/error'

const auth = useAuthStore()
const loading = ref(false)
const classes = ref<TeachingClass[]>([])
const subjects = ref<CourseSubject[]>([])
const terms = ref<AcademicTerm[]>([])
const courses = ref<Course[]>([])
const pendingTeachers = ref<User[]>([])
const joinCode = ref('')
const createVisible = ref(false)
const setupVisible = ref(false)
const manageVisible = ref(false)
const selected = ref<TeachingClass | null>(null)
const members = ref<ClassMember[]>([])
const requests = ref<ClassRequest[]>([])
const groups = ref<ClassGroup[]>([])
const randomCount = ref(4)
const availableTeachers = ref<AvailableTeacher[]>([])
const collaboratorId = ref<number>()
const extraMaterialId = ref<number>()
const extraMaterialRole = ref<'primary' | 'supplementary'>('supplementary')
const form = reactive({ subject_id: 0, term_id: 0, name: '', code: '', description: '', primary_course_id: 0, supplementary_course_ids: [] as number[] })
const subjectForm = reactive({ name: '习近平新时代中国特色社会主义思想概论', code: 'XG', description: '' })
const termForm = reactive({ name: '', start_date: '', end_date: '', is_current: true })
const isManager = computed(() => auth.user?.role === 'teacher' || auth.user?.role === 'admin')

async function load() {
  loading.value = true
  try {
    const [classRes, subjectRes, termRes, courseRes] = await Promise.all([
      teachingClassApi.list(), teachingClassApi.subjects(), teachingClassApi.terms(), courseApi.list(),
    ])
    classes.value = classRes.data.data; subjects.value = subjectRes.data.data; terms.value = termRes.data.data; courses.value = courseRes.data.data
    if (auth.isAdmin) pendingTeachers.value = (await authApi.pendingTeachers()).data.data
  } catch (error) { ElMessage.error(getErrorMessage(error, '教学班数据加载失败')) }
  finally { loading.value = false }
}

function openCreate() {
  if (!subjects.value.length || !terms.value.length) { setupVisible.value = true; return }
  Object.assign(form, { subject_id: subjects.value[0].id, term_id: terms.value.find(item => item.is_current)?.id || terms.value[0].id,
    name: '', code: '', description: '', primary_course_id: courses.value[0]?.id || 0, supplementary_course_ids: [] })
  createVisible.value = true
}

async function createClass() {
  try { await teachingClassApi.create({ ...form }); ElMessage.success('教学班已创建'); createVisible.value = false; await load() }
  catch (error) { ElMessage.error(getErrorMessage(error, '创建失败')) }
}

async function join() {
  if (!joinCode.value.trim()) return
  try { const { data } = await teachingClassApi.join(joinCode.value); ElMessage.success(data.data.message); joinCode.value = ''; await load() }
  catch (error) { ElMessage.error(getErrorMessage(error, '加入失败')) }
}

async function leave(item: TeachingClass) {
  await ElMessageBox.confirm(`退出“${item.name}”后将停止接收新任务，历史学习记录会保留。`, '退出教学班')
  try { const { data } = await teachingClassApi.leave(item.id); ElMessage.success(data.data.message); await load() }
  catch (error) { ElMessage.error(getErrorMessage(error, '退出失败')) }
}

async function openManage(item: TeachingClass) {
  selected.value = item; manageVisible.value = true
  try {
    const [memberRes, requestRes, groupRes, teacherRes] = await Promise.all([
      teachingClassApi.members(item.id), teachingClassApi.requests(item.id), teachingClassApi.groups(item.id), teachingClassApi.availableTeachers(),
    ])
    members.value = memberRes.data.data; requests.value = requestRes.data.data; groups.value = groupRes.data.data
    availableTeachers.value = teacherRes.data.data.filter((teacher) => teacher.id !== auth.user?.id)
  } catch (error) { ElMessage.error(getErrorMessage(error, '班级详情加载失败')) }
}

async function addCollaborator() {
  if (!selected.value || !collaboratorId.value) return
  try { await teachingClassApi.addTeacher(selected.value.id, collaboratorId.value); collaboratorId.value = undefined; ElMessage.success('协作教师已添加') }
  catch (error) { ElMessage.error(getErrorMessage(error, '添加协作教师失败')) }
}

async function addMaterial() {
  if (!selected.value || !extraMaterialId.value) return
  try {
    await teachingClassApi.addMaterial(selected.value.id, extraMaterialId.value, extraMaterialRole.value)
    ElMessage.success('教学班教材已更新'); extraMaterialId.value = undefined; await load()
    selected.value = classes.value.find((item) => item.id === selected.value?.id) || selected.value
  } catch (error) { ElMessage.error(getErrorMessage(error, '添加教材失败')) }
}

async function changeStatus(value: TeachingClass['status']) {
  if (!selected.value) return
  await teachingClassApi.updateStatus(selected.value.id, value); selected.value.status = value
  ElMessage.success('教学班状态已更新'); await load()
}

async function review(request: ClassRequest, approved: boolean) {
  await teachingClassApi.reviewRequest(request.id, approved); ElMessage.success('申请已处理'); if (selected.value) await openManage(selected.value)
}

async function uploadRoster(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !selected.value) return
  try { const { data } = await teachingClassApi.roster(selected.value.id, file); ElMessage.success(`名单已导入，成功绑定 ${data.data.bound} 人`); await openManage(selected.value) }
  catch (error) { ElMessage.error(getErrorMessage(error, '名单导入失败')) }
}

async function randomGroup() {
  if (!selected.value) return
  try { const { data } = await teachingClassApi.randomGroups(selected.value.id, randomCount.value); groups.value = data.data; ElMessage.success('随机分组完成') }
  catch (error) { ElMessage.error(getErrorMessage(error, '分组失败')) }
}

async function regenerateCode() {
  if (!selected.value) return
  const { data } = await teachingClassApi.updateJoinCode(selected.value.id, { regenerate: true })
  selected.value.join_code = data.data.join_code; ElMessage.success('班级码已更新')
}

async function approveTeacher(user: User, approved: boolean) {
  await authApi.reviewTeacher(user.id, approved ? 'approved' : 'rejected')
  ElMessage.success('教师审核已处理'); await load()
}

async function createSubjectAndTerm() {
  try {
    if (!subjects.value.length) await teachingClassApi.createSubject(subjectForm)
    if (!terms.value.length) await teachingClassApi.createTerm(termForm)
    setupVisible.value = false; await load(); openCreate()
  } catch (error) { ElMessage.error(getErrorMessage(error, '基础数据创建失败')) }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="class-hub-page">
    <section class="class-hub-hero">
      <div><p class="eyebrow">AI Teaching Class</p><h1>课程教学班</h1><p>同一课程、同一学期只加入一个教学班；教材、任务、互动与学习统计都在班级边界内运行。</p></div>
      <div class="class-hub-actions">
        <el-button v-if="isManager" type="primary" size="large" :icon="Plus" @click="openCreate">创建教学班</el-button>
        <el-button v-if="auth.isAdmin" size="large" @click="setupVisible = true">课程与学期设置</el-button>
      </div>
    </section>

    <section v-if="auth.user?.role === 'student'" class="class-join-panel">
      <div><el-icon><School /></el-icon><div><h2>加入新的教学班</h2><p>输入教师提供的班级码；名单内学号自动通过，名单外申请需要审核。</p></div></div>
      <el-input v-model="joinCode" maxlength="16" placeholder="请输入班级码" size="large" @keyup.enter="join"><template #append><el-button @click="join">加入</el-button></template></el-input>
    </section>

    <section v-if="auth.isAdmin && pendingTeachers.length" class="teacher-review-panel">
      <div class="section-heading"><div><p class="eyebrow">Teacher Verification</p><h2>待审核教师</h2></div><el-tag type="warning">{{ pendingTeachers.length }} 人</el-tag></div>
      <div class="teacher-review-list"><article v-for="teacher in pendingTeachers" :key="teacher.id"><div><strong>{{ teacher.username }}</strong><span>工号 {{ teacher.identity_no }}</span></div><div><el-button type="success" @click="approveTeacher(teacher, true)">通过</el-button><el-button @click="approveTeacher(teacher, false)">拒绝</el-button></div></article></div>
    </section>

    <section class="class-grid-section">
      <div class="section-heading"><div><p class="eyebrow">My Classes</p><h2>{{ isManager ? '我管理的教学班' : '我加入的教学班' }}</h2></div><el-button :icon="Refresh" circle @click="load" /></div>
      <div v-if="classes.length" class="class-card-grid">
        <article v-for="item in classes" :key="item.id" class="class-card">
          <div class="class-card-top"><span>{{ item.term_name }}</span><div><el-tag :type="item.status === 'active' ? 'success' : 'info'">{{ item.status }}</el-tag><el-tag v-if="!isManager && item.membership_status !== 'active'" type="warning" style="margin-left:6px">{{ item.membership_status }}</el-tag></div></div>
          <div class="class-card-icon"><el-icon><Collection /></el-icon></div>
          <h3>{{ item.name }}</h3><p>{{ item.subject_name }}</p>
          <dl><div><dt>教材</dt><dd>{{ item.material_ids.length }} 本</dd></div><div><dt>学生</dt><dd>{{ item.student_count }} 人</dd></div><div><dt>班级码</dt><dd>{{ isManager ? item.join_code : '已加入' }}</dd></div></dl>
          <div class="class-card-actions"><el-button v-if="isManager" type="primary" @click="openManage(item)">管理班级</el-button><el-button v-else-if="item.membership_status === 'active' && item.status !== 'archived'" @click="leave(item)">退出班级</el-button><span v-else-if="item.membership_status === 'pending'" class="muted">等待主讲教师审核</span><span v-else class="muted">历史班级，仅供查看</span></div>
        </article>
      </div>
      <el-empty v-else description="暂无教学班" />
    </section>

    <el-dialog v-model="createVisible" title="创建教学班" width="620px">
      <el-form :model="form" label-position="top">
        <el-row :gutter="16"><el-col :span="12"><el-form-item label="课程科目"><el-select v-model="form.subject_id"><el-option v-for="item in subjects" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item></el-col><el-col :span="12"><el-form-item label="学期"><el-select v-model="form.term_id"><el-option v-for="item in terms" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item></el-col></el-row>
        <el-row :gutter="16"><el-col :span="16"><el-form-item label="教学班名称"><el-input v-model="form.name" placeholder="例如：2026秋季一班" /></el-form-item></el-col><el-col :span="8"><el-form-item label="班级编号"><el-input v-model="form.code" placeholder="01" /></el-form-item></el-col></el-row>
        <el-form-item label="主教材"><el-select v-model="form.primary_course_id"><el-option v-for="item in courses" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="补充教材"><el-select v-model="form.supplementary_course_ids" multiple><el-option v-for="item in courses.filter(c => c.id !== form.primary_course_id)" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" /></el-form-item>
      </el-form><template #footer><el-button @click="createVisible=false">取消</el-button><el-button type="primary" @click="createClass">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="setupVisible" title="课程科目与学期" width="620px">
      <el-alert title="首次使用时创建一次即可，后续教学班直接复用。" type="info" :closable="false" />
      <el-form label-position="top"><template v-if="!subjects.length"><el-divider>课程科目</el-divider><el-form-item label="名称"><el-input v-model="subjectForm.name" /></el-form-item><el-form-item label="代码"><el-input v-model="subjectForm.code" /></el-form-item></template><template v-if="!terms.length"><el-divider>当前学期</el-divider><el-form-item label="名称"><el-input v-model="termForm.name" placeholder="2026秋季学期" /></el-form-item><el-row :gutter="12"><el-col :span="12"><el-form-item label="开始日期"><el-date-picker v-model="termForm.start_date" value-format="YYYY-MM-DD" /></el-form-item></el-col><el-col :span="12"><el-form-item label="结束日期"><el-date-picker v-model="termForm.end_date" value-format="YYYY-MM-DD" /></el-form-item></el-col></el-row></template></el-form>
      <template #footer><el-button @click="setupVisible=false">关闭</el-button><el-button type="primary" @click="createSubjectAndTerm">保存</el-button></template>
    </el-dialog>

    <el-drawer v-model="manageVisible" :title="selected?.name" size="720px" class="class-manage-drawer">
      <section v-if="selected" class="class-code-box"><div><span>班级码</span><strong>{{ selected.join_code }}</strong></div><el-button :icon="Refresh" @click="regenerateCode">重新生成</el-button></section>
      <el-tabs>
        <el-tab-pane label="学生成员"><div class="drawer-toolbar"><label class="roster-upload"><el-icon><UploadFilled /></el-icon> 导入 Excel/CSV<input type="file" accept=".xlsx,.csv" @change="uploadRoster" /></label></div><el-table :data="members"><el-table-column prop="username" label="姓名/账号" /><el-table-column prop="identity_no" label="学号" /><el-table-column prop="join_method" label="加入方式" /><el-table-column prop="status" label="状态" /></el-table></el-tab-pane>
        <el-tab-pane :label="`待审核 ${requests.length}`"><el-empty v-if="!requests.length" description="暂无待审核申请" /><div v-for="item in requests" :key="item.id" class="request-row"><div><strong>{{ item.username }}</strong><span>{{ item.identity_no }} · {{ item.request_type }}</span></div><div><el-button type="success" @click="review(item,true)">通过</el-button><el-button @click="review(item,false)">拒绝</el-button></div></div></el-tab-pane>
        <el-tab-pane label="学习小组"><div class="drawer-toolbar"><el-input-number v-model="randomCount" :min="2" :max="30" /><el-button type="primary" :icon="UserFilled" @click="randomGroup">随机分组</el-button></div><article v-for="group in groups" :key="group.id" class="group-row"><strong>{{ group.name }}</strong><span>{{ group.user_ids.length }} 人</span></article><el-empty v-if="!groups.length" description="尚未分组" /></el-tab-pane>
        <el-tab-pane label="教师与教材">
          <el-divider content-position="left">协作教师</el-divider><div class="drawer-toolbar"><el-select v-model="collaboratorId" filterable placeholder="选择已审核教师" style="flex:1"><el-option v-for="teacher in availableTeachers" :key="teacher.id" :label="`${teacher.username} · ${teacher.identity_no || '无工号'}`" :value="teacher.id" /></el-select><el-button type="primary" @click="addCollaborator">添加</el-button></div>
          <el-divider content-position="left">绑定教材</el-divider><div class="drawer-toolbar"><el-select v-model="extraMaterialId" placeholder="选择教材" style="flex:1"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select><el-select v-model="extraMaterialRole" style="width:130px"><el-option label="主教材" value="primary" /><el-option label="补充教材" value="supplementary" /></el-select><el-button type="primary" @click="addMaterial">保存</el-button></div><el-tag v-for="courseId in selected?.material_ids" :key="courseId" class="class-material-tag">{{ courses.find((course) => course.id === courseId)?.name || courseId }}</el-tag>
          <el-divider content-position="left">教学班状态</el-divider><el-radio-group :model-value="selected?.status" @change="changeStatus($event as TeachingClass['status'])"><el-radio-button value="not_started">未开始</el-radio-button><el-radio-button value="active">进行中</el-radio-button><el-radio-button value="completed">已结课</el-radio-button><el-radio-button value="archived">已归档</el-radio-button></el-radio-group>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>
  </div>
</template>
