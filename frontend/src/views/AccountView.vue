<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, Bell, Calendar, Check, EditPen, Key, Location, MapLocation, Message, Monitor, School, Setting, User } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const auth = useAuthStore()
type SettingSection = 'profile' | 'security' | 'preferences'
const activeSection = ref<SettingSection>('profile')
const emailFormRef = ref<FormInstance>()
const passwordFormRef = ref<FormInstance>()
const emailLoading = ref(false)
const verifying = ref(false)
const passwordLoading = ref(false)
const sent = ref(false)
const passwordDialogVisible = ref(false)
const profileFormRef = ref<FormInstance>()
const avatarInput = ref<HTMLInputElement>()
const form = reactive({ email: auth.user?.email || '', code: '' })
const profileForm = reactive({
  name: localStorage.getItem('account_profile_name') || auth.user?.username || '',
  birthDate: localStorage.getItem('account_profile_birth_date') || '',
  university: localStorage.getItem('account_profile_university') || '',
  city: localStorage.getItem('account_profile_city') || '',
  address: localStorage.getItem('account_profile_address') || '',
  bio: localStorage.getItem('account_profile_bio') || '',
  avatar: localStorage.getItem('account_profile_avatar') || '',
})
const passwordForm = reactive({ password: '', confirmPassword: '' })
const preferences = reactive({
  learningReminder: localStorage.getItem('account_learning_reminder') !== 'false',
  productUpdates: localStorage.getItem('account_product_updates') === 'true',
  compactMode: localStorage.getItem('account_compact_mode') === 'true',
})
const emailRules: FormRules = {
  email: [{ required: true, type: 'email', message: '请输入有效邮箱', trigger: 'blur' }],
  code: [{ required: true, len: 6, pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }],
}
const passwordRules: FormRules = {
  password: [{ required: true, min: 8, max: 128, message: '密码长度为 8～128 个字符', trigger: 'blur' }],
  confirmPassword: [{ required: true, validator: (_rule, value, callback) => callback(value === passwordForm.password ? undefined : new Error('两次输入的密码不一致')), trigger: 'blur' }],
}
const profileRules: FormRules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  birthDate: [{ required: true, message: '请选择出生日期', trigger: 'change' }],
  university: [{ required: true, message: '请输入大学名称', trigger: 'blur' }],
  city: [{ required: true, message: '请输入所在城市', trigger: 'blur' }],
  address: [{ required: true, message: '请输入地址', trigger: 'blur' }],
}
const verified = computed(() => Boolean(auth.user?.email_verified_at))
const roleLabel = computed(() => ({ student: '学生', teacher: '教师', admin: '管理员' }[auth.user?.role || 'student']))
const initials = computed(() => (auth.user?.username || 'U').slice(0, 1).toUpperCase())
const avatarSource = computed(() => profileForm.avatar)
const emailStatus = computed(() => verified.value ? { label: '已验证', tone: 'success' } : form.email ? { label: '待验证', tone: 'warning' } : { label: '未绑定', tone: 'neutral' })
const currentSection = computed(() => ({
  profile: { title: '个人资料', description: '查看你的账号身份信息和绑定方式。' },
  security: { title: '安全设置', description: '管理密码和账号恢复方式，保持账号安全。' },
  preferences: { title: '通知偏好', description: '选择你希望接收的学习和平台提醒。' },
}[activeSection.value]))

watch(preferences, (value) => {
  localStorage.setItem('account_learning_reminder', String(value.learningReminder))
  localStorage.setItem('account_product_updates', String(value.productUpdates))
  localStorage.setItem('account_compact_mode', String(value.compactMode))
}, { deep: true })

function selectSection(section: SettingSection) { activeSection.value = section }
function openAvatarPicker() { avatarInput.value?.click() }
function onAvatarChange(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (!['image/png', 'image/jpeg'].includes(file.type)) { ElMessage.error('头像仅支持 PNG 或 JPEG 格式'); return }
  if (file.size > 2 * 1024 * 1024) { ElMessage.error('头像大小不能超过 2MB'); return }
  const reader = new FileReader()
  reader.onload = () => { profileForm.avatar = String(reader.result || '') }
  reader.readAsDataURL(file)
}
async function saveProfile() {
  if (!(await profileFormRef.value?.validate())) return
  localStorage.setItem('account_profile_name', profileForm.name)
  localStorage.setItem('account_profile_birth_date', profileForm.birthDate)
  localStorage.setItem('account_profile_university', profileForm.university)
  localStorage.setItem('account_profile_city', profileForm.city)
  localStorage.setItem('account_profile_address', profileForm.address)
  localStorage.setItem('account_profile_bio', profileForm.bio)
  if (profileForm.avatar) localStorage.setItem('account_profile_avatar', profileForm.avatar)
  ElMessage.success('基础信息已保存到当前浏览器')
}
async function submitEmail() {
  if (!(await emailFormRef.value?.validate())) return
  emailLoading.value = true
  try { await authApi.requestEmailVerification(form.email); sent.value = true; await auth.loadCurrentUser(); ElMessage.success('验证码邮件已发送') }
  catch (error: unknown) { ElMessage.error(getErrorMessage(error, '发送失败，请稍后重试')) }
  finally { emailLoading.value = false }
}
async function confirmEmail() {
  if (!(await emailFormRef.value?.validateField('code'))) return
  verifying.value = true
  try { await authApi.confirmEmailVerification(form.email, form.code); sent.value = false; form.code = ''; await auth.loadCurrentUser(); ElMessage.success('邮箱验证成功') }
  catch (error: unknown) { ElMessage.error(getErrorMessage(error, '验证码无效或已过期')) }
  finally { verifying.value = false }
}
function openPasswordDialog() { passwordForm.password = ''; passwordForm.confirmPassword = ''; passwordDialogVisible.value = true }
async function submitPassword() {
  if (!(await passwordFormRef.value?.validate())) return
  passwordLoading.value = true
  try { await authApi.changePassword(passwordForm.password); passwordDialogVisible.value = false; auth.logout(); ElMessage.success('密码修改成功，请重新登录'); await router.push('/login') }
  catch (error: unknown) { ElMessage.error(getErrorMessage(error, '修改失败，请稍后重试')) }
  finally { passwordLoading.value = false }
}
async function copyIdentity() {
  const identity = auth.user?.identity_no
  if (!identity) return
  try { await navigator.clipboard.writeText(identity); ElMessage.success('身份编号已复制') }
  catch { ElMessage.info(`身份编号：${identity}`) }
}
</script>

<template>
  <div class="account-page">
    <div class="settings-layout">
      <aside class="settings-nav" aria-label="账号设置导航">
        <div class="settings-nav__profile"><span class="profile-avatar">{{ initials }}</span><div><strong>{{ auth.user?.username }}</strong><span>{{ roleLabel }} · {{ auth.user?.identity_no || '未填写身份编号' }}</span></div></div>
        <button type="button" :class="{ active: activeSection === 'profile' }" @click="selectSection('profile')"><el-icon><User /></el-icon><span>个人资料</span><el-icon class="nav-arrow"><ArrowRight /></el-icon></button>
        <button type="button" :class="{ active: activeSection === 'security' }" @click="selectSection('security')"><el-icon><Lock /></el-icon><span>安全设置</span><el-icon class="nav-arrow"><ArrowRight /></el-icon></button>
        <button type="button" :class="{ active: activeSection === 'preferences' }" @click="selectSection('preferences')"><el-icon><Setting /></el-icon><span>通知偏好</span><el-icon class="nav-arrow"><ArrowRight /></el-icon></button>
        <div class="settings-nav__footer"><el-icon><Message /></el-icon><span>需要帮助？<br><a href="mailto:support@szjy.local">联系平台支持</a></span></div>
      </aside>
      <main class="settings-content">
        <div class="content-title"><div><p class="account-kicker">{{ activeSection.toUpperCase() }}</p><h2>{{ currentSection.title }}</h2><p>{{ currentSection.description }}</p></div><el-button class="settings-exit" text :icon="ArrowLeft" @click="router.push('/')">退出设置</el-button></div>
        <section v-if="activeSection === 'profile'" class="settings-section">
          <div class="section-card profile-card">
            <div class="card-heading"><div><h3>基础信息</h3><p>完善个人资料，让课程协作和学习记录更清晰。</p></div><el-tag effect="plain" type="info">本机保存</el-tag></div>
            <div class="avatar-editor">
              <div class="avatar-preview"><img v-if="avatarSource" :src="avatarSource" alt="个人头像" /><span v-else>{{ initials }}</span></div>
              <div class="avatar-copy"><strong>上传图片</strong><p>最小尺寸 400×400 像素，支持 PNG 或 JPEG，最大 2MB。</p><input ref="avatarInput" class="sr-only" type="file" accept="image/png,image/jpeg" @change="onAvatarChange" /><el-button plain @click="openAvatarPicker">{{ avatarSource ? '更换头像' : '上传头像' }}</el-button></div>
            </div>
            <el-form ref="profileFormRef" :model="profileForm" :rules="profileRules" label-position="top" class="profile-form">
              <div class="profile-form-grid">
                <el-form-item label="姓名" prop="name"><el-input v-model="profileForm.name" size="large" :prefix-icon="User" placeholder="请输入姓名" /></el-form-item>
                <el-form-item label="出生日期" prop="birthDate"><el-date-picker v-model="profileForm.birthDate" type="date" value-format="YYYY-MM-DD" size="large" placeholder="请选择出生日期" :prefix-icon="Calendar" /></el-form-item>
                <el-form-item label="电子邮件" required><el-input :model-value="auth.user?.email || '尚未绑定邮箱'" size="large" readonly :prefix-icon="Message" /></el-form-item>
                <el-form-item label="大学名称" prop="university"><el-input v-model="profileForm.university" size="large" :prefix-icon="School" placeholder="请输入大学名称" /></el-form-item>
                <el-form-item label="城市" prop="city"><el-input v-model="profileForm.city" size="large" :prefix-icon="Location" placeholder="请输入所在城市" /></el-form-item>
                <el-form-item label="地址" prop="address" class="profile-form-item--full"><el-input v-model="profileForm.address" size="large" :prefix-icon="MapLocation" placeholder="请输入详细地址" /></el-form-item>
                <el-form-item label="传记" class="profile-form-item--full"><el-input v-model="profileForm.bio" type="textarea" :rows="4" maxlength="200" show-word-limit placeholder="请描述一下你自己……" /></el-form-item>
              </div>
              <div class="profile-form-footer"><span>姓名、出生日期、学校和地址仅保存在当前浏览器。</span><el-button type="primary" @click="saveProfile">保存基础信息</el-button></div>
            </el-form>
          </div>
          <div class="section-card email-card"><div class="card-heading"><div><h3>找回邮箱</h3><p>邮箱用于密码找回和安全验证，不用于登录。</p></div><span :class="['status-pill', `status-pill--${emailStatus.tone}`]"><el-icon v-if="verified"><Check /></el-icon>{{ emailStatus.label }}</span></div><el-alert v-if="verified" type="success" :closable="false" title="邮箱已验证，可用于自助找回密码" /><el-alert v-else-if="sent" type="info" :closable="false" title="验证码邮件已发送，请查收邮箱" /><el-form ref="emailFormRef" :model="form" :rules="emailRules" label-position="top" @keyup.enter="sent ? confirmEmail() : submitEmail()"><div class="email-form-grid"><el-form-item label="邮箱地址" prop="email"><el-input v-model="form.email" type="email" autocomplete="email" placeholder="请输入常用邮箱" size="large" :disabled="emailLoading" /></el-form-item><el-form-item v-if="sent" label="验证码" prop="code"><el-input v-model="form.code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="6 位数字" size="large" :disabled="verifying" /></el-form-item></div><div class="form-actions"><el-button v-if="!sent || verified" type="primary" :loading="emailLoading" @click="submitEmail">{{ verified ? '更换邮箱' : '发送验证码' }}</el-button><el-button v-if="sent" type="primary" :loading="verifying" @click="confirmEmail">确认验证</el-button></div></el-form></div>
        </section>
        <section v-else-if="activeSection === 'security'" class="settings-section"><div class="section-card security-card"><div class="card-heading"><div><h3>登录密码</h3><p>定期更新密码可以降低账号被盗风险。</p></div><span class="security-icon"><el-icon><Key /></el-icon></span></div><div class="security-row"><div><strong>密码</strong><span>建议使用 8 位以上且包含字母和数字的密码</span></div><el-button type="primary" plain :icon="EditPen" @click="openPasswordDialog">修改密码</el-button></div></div><div class="section-card security-card"><div class="card-heading"><div><h3>登录设备</h3><p>当前仅显示本次登录的浏览器会话。</p></div><span class="security-icon security-icon--green"><el-icon><Monitor /></el-icon></span></div><div class="device-row"><span class="device-icon"><el-icon><Monitor /></el-icon></span><div><strong>当前浏览器</strong><span>本设备 · 活跃</span></div><span class="device-current">当前会话</span></div></div><el-alert type="info" :closable="false" show-icon title="发现异常登录？" description="请立即修改密码，并联系平台管理员检查账号活动。" /></section>
        <section v-else class="settings-section"><div class="section-card preference-card"><div class="card-heading"><div><h3>提醒设置</h3><p>提醒会显示在平台消息中心，不会影响课程功能。</p></div><span class="security-icon security-icon--gold"><el-icon><Bell /></el-icon></span></div><div class="preference-row"><div><strong>学习进度提醒</strong><span>有待完成的学习任务时提醒我</span></div><el-switch v-model="preferences.learningReminder" /></div><div class="preference-row"><div><strong>平台更新通知</strong><span>接收新功能和平台维护信息</span></div><el-switch v-model="preferences.productUpdates" /></div></div><div class="section-card preference-card"><div class="card-heading"><div><h3>显示偏好</h3><p>仅保存在当前浏览器，不会同步到其他设备。</p></div><span class="security-icon"><el-icon><Setting /></el-icon></span></div><div class="preference-row"><div><strong>紧凑显示</strong><span>减少列表间距，查看更多内容</span></div><el-switch v-model="preferences.compactMode" /></div></div></section>
      </main>
    </div>
    <el-dialog v-model="passwordDialogVisible" title="修改登录密码" width="min(92vw, 460px)" destroy-on-close><p class="dialog-description">设置新密码后，当前会话会退出，请使用新密码重新登录。</p><el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-position="top" @keyup.enter="submitPassword"><el-form-item label="新密码" prop="password"><el-input v-model="passwordForm.password" type="password" show-password autocomplete="new-password" size="large" /></el-form-item><el-form-item label="确认新密码" prop="confirmPassword"><el-input v-model="passwordForm.confirmPassword" type="password" show-password autocomplete="new-password" size="large" /></el-form-item></el-form><template #footer><el-button @click="passwordDialogVisible = false">取消</el-button><el-button type="primary" :loading="passwordLoading" @click="submitPassword">确认修改</el-button></template></el-dialog>
  </div>
</template>

<style scoped>
.settings-nav > button > .el-icon:first-child { width: 20px; font-size: 19px; filter: drop-shadow(0 1px 0 rgb(255 255 255 / 80%)); }
.settings-nav > button.active > .el-icon:first-child { filter: drop-shadow(0 1px 1px rgb(89 65 115 / 24%)); }
.settings-nav__footer > .el-icon { font-size: 18px; }
.account-page { max-width: 1120px; margin: 0 auto; padding-bottom: var(--space-8); }.account-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-6); margin-bottom: var(--space-6); }.account-kicker { margin: 0; color: #594173; font-size: var(--fs-meta); font-weight: var(--fw-bold); letter-spacing: .12em; }.account-heading h1 { margin: 6px 0 4px; font-size: var(--fs-page-title); }.account-heading__description, .content-title p { margin: 0; color: var(--ink-600); line-height: 1.6; }.account-heading__status { display: flex; align-items: center; gap: 7px; color: #52705b; font-size: var(--fs-aux); white-space: nowrap; }.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #2d9957; box-shadow: 0 0 0 4px #e4f3e8; }
.settings-layout { display: grid; grid-template-columns: 248px minmax(0, 1fr); align-items: start; gap: 28px; }.settings-nav { position: sticky; top: 24px; padding: 10px 0; border-right: 1px solid #eae7ee; }.settings-nav__profile { display: flex; align-items: center; gap: 12px; padding: 8px 20px 22px 4px; }.settings-nav__profile div, .profile-summary div, .device-row div { display: grid; gap: 3px; min-width: 0; }.settings-nav__profile strong { overflow: hidden; text-overflow: ellipsis; }.settings-nav__profile span:last-child, .profile-summary span, .device-row span { color: var(--ink-400); font-size: var(--fs-meta); }.profile-avatar { display: grid; flex: none; width: 40px; height: 40px; place-items: center; color: #fff; background: #594173; border-radius: 50%; font-weight: var(--fw-bold); }.profile-avatar--large { width: 56px; height: 56px; font-size: 20px; }.settings-nav > button { display: flex; align-items: center; width: calc(100% - 12px); margin: 3px 0; padding: 11px 14px; color: var(--ink-600); background: transparent; border: 0; border-radius: 8px; text-align: left; cursor: pointer; }.settings-nav > button:hover { background: #f7f4fa; color: #594173; }.settings-nav > button.active { color: #594173; background: #f1eaff; font-weight: var(--fw-medium); }.settings-nav > button > span { margin-left: 10px; }.settings-nav .nav-arrow { margin-left: auto; font-size: 13px; opacity: .55; }.settings-nav__footer { display: flex; gap: 9px; margin: 40px 20px 0 4px; padding-top: 18px; border-top: 1px solid #eae7ee; color: var(--ink-400); font-size: var(--fs-meta); line-height: 1.6; }.settings-nav__footer .el-icon { margin-top: 2px; color: #594173; }.settings-nav__footer a { color: #594173; text-decoration: none; }
.settings-content { min-width: 0; }.content-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 6px 0 20px; border-bottom: 1px solid #eae7ee; }.content-title h2 { margin: 5px 0 4px; font-size: 22px; }.settings-exit { flex: none; margin-top: 8px; color: #594173; }.settings-section { display: grid; gap: 16px; padding-top: 20px; }.section-card { padding: 22px 24px; background: #fff; border: 1px solid #eae7ee; border-radius: 10px; box-shadow: 0 1px 3px rgb(43 15 73 / 4%); }.card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }.card-heading h3 { margin: 0 0 4px; font-size: var(--fs-card-title); color: #2b0f49; }.card-heading p { margin: 0; color: var(--ink-400); font-size: var(--fs-aux); }
.avatar-editor { display: flex; align-items: center; gap: 22px; padding: 6px 0 24px; border-bottom: 1px solid #f0edf3; }.avatar-preview { display: grid; width: 96px; height: 96px; flex: none; place-items: center; overflow: hidden; color: #fff; background: linear-gradient(145deg, #eeeaf3, #d9d3e2); border-radius: 50%; font-size: 30px; font-weight: var(--fw-bold); }.avatar-preview img { width: 100%; height: 100%; object-fit: cover; }.avatar-copy { display: grid; gap: 5px; }.avatar-copy strong { color: #2b0f49; font-size: 17px; }.avatar-copy p { margin: 0 0 6px; color: var(--ink-400); font-size: var(--fs-aux); }.profile-form { margin-top: 22px; }.profile-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px 18px; }.profile-form-grid .el-form-item { margin-bottom: 16px; }.profile-form-item--full { grid-column: 1 / -1; }.profile-form .el-date-editor { width: 100%; }.profile-form-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 4px; }.profile-form-footer span { color: var(--ink-400); font-size: var(--fs-meta); }.profile-summary { display: flex; align-items: center; gap: 14px; padding-bottom: 20px; border-bottom: 1px solid #f0edf3; }.profile-summary strong { color: #2b0f49; font-size: 18px; }.info-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px 32px; padding-top: 20px; }.info-item { display: grid; gap: 4px; min-width: 0; }.info-item span { color: var(--ink-400); font-size: var(--fs-meta); }.info-item strong { display: flex; align-items: center; color: #2b0f49; font-size: var(--fs-body); font-weight: var(--fw-medium); }.info-item .el-button { margin-left: 4px; color: #594173; }.email-card .el-alert { margin-bottom: 18px; }.email-form-grid { display: grid; grid-template-columns: minmax(0, 1fr) 180px; gap: 16px; }.email-form-grid .el-form-item { margin-bottom: 12px; }.form-actions { display: flex; gap: 10px; }.status-pill { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 4px; font-size: var(--fs-meta); white-space: nowrap; }.status-pill--success { color: #207343; background: #e8f5eb; }.status-pill--warning { color: #9b681b; background: #fff7e5; }.status-pill--neutral { color: var(--ink-600); background: #f1f2f4; }
.security-icon { display: grid; width: 34px; height: 34px; place-items: center; color: #594173; background: #f1eaff; border-radius: 8px; font-size: 17px; }.security-icon--green { color: #2a8251; background: #e8f5eb; }.security-icon--gold { color: #9b681b; background: #fff7e5; }.security-row, .device-row, .preference-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 18px; border-top: 1px solid #f0edf3; }.security-row div, .preference-row div { display: grid; gap: 4px; }.security-row strong, .preference-row strong, .device-row strong { color: #2b0f49; font-weight: var(--fw-medium); }.security-row span, .preference-row span, .device-row span { color: var(--ink-400); font-size: var(--fs-meta); }.device-row { justify-content: flex-start; }.device-icon { display: grid; width: 38px; height: 38px; place-items: center; color: #594173; background: #f7f4fa; border-radius: 8px; font-size: 18px; }.device-current { margin-left: auto; color: #2a8251 !important; }.dialog-description { margin: -4px 0 18px; color: var(--ink-600); line-height: 1.6; }
.section-card { position: relative; border-color: #e1dbe8; box-shadow: inset 0 1px 0 rgb(255 255 255 / 90%), 0 2px 0 #d8d0e1, 0 8px 20px rgb(43 15 73 / 9%); transition: transform .18s ease, box-shadow .18s ease; }
.section-card:hover { transform: translateY(-1px); box-shadow: inset 0 1px 0 rgb(255 255 255 / 90%), 0 3px 0 #d8d0e1, 0 12px 24px rgb(43 15 73 / 12%); }
.profile-form :deep(.el-input__wrapper), .profile-form :deep(.el-textarea__inner) { border: 1px solid #e4dfea; box-shadow: inset 0 1px 0 rgb(255 255 255 / 90%), 0 2px 5px rgb(43 15 73 / 9%); }
.profile-form :deep(.el-input__wrapper.is-focus), .profile-form :deep(.el-input__wrapper:focus-within), .profile-form :deep(.el-textarea__inner:focus) { border-color: #a78cbc; box-shadow: 0 0 0 2px rgb(89 65 115 / 13%), inset 0 1px 0 rgb(255 255 255 / 90%), 0 3px 8px rgb(43 15 73 / 12%); }
.profile-form :deep(.el-input__prefix .el-icon), .security-icon .el-icon, .device-icon .el-icon { font-size: 19px; filter: drop-shadow(0 1px 0 rgb(255 255 255 / 85%)); }
@media (max-width: 800px) { .settings-layout { grid-template-columns: 1fr; gap: 16px; }.settings-nav { position: static; display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; padding: 0 0 10px; border-right: 0; border-bottom: 1px solid #eae7ee; }.settings-nav__profile, .settings-nav__footer { grid-column: 1 / -1; }.settings-nav__profile { padding: 0 0 12px; }.settings-nav__footer { display: none; }.settings-nav > button { width: 100%; justify-content: center; padding: 10px 8px; }.settings-nav > button > span { margin-left: 6px; }.settings-nav .nav-arrow { display: none; } }
@media (max-width: 560px) { .account-heading { align-items: flex-start; flex-direction: column; gap: 10px; }.section-card { padding: 18px 16px; }.info-grid, .email-form-grid, .profile-form-grid { grid-template-columns: 1fr; gap: 12px; }.card-heading { margin-bottom: 16px; }.settings-nav > button { font-size: 12px; }.avatar-editor { align-items: flex-start; gap: 14px; }.avatar-preview { width: 72px; height: 72px; font-size: 24px; }.profile-form-footer { align-items: flex-start; flex-direction: column; }.profile-form-footer .el-button { width: 100%; }.security-row, .preference-row { align-items: flex-start; }.security-row .el-button { flex: none; }.device-current { align-self: center; } }

/* 红色阶覆盖：账号设置页同步使用参考图 Color 10–50。 */
.account-kicker,
.settings-nav > button:hover,
.settings-nav > button.active,
.settings-nav__footer .el-icon,
.settings-nav__footer a,
.settings-exit,
.info-item .el-button { color: var(--brand-primary); }
.profile-avatar { background: var(--brand-primary); }
.card-heading h3, .avatar-copy strong, .profile-summary strong, .info-item strong, .security-row strong, .preference-row strong, .device-row strong { color: var(--ink-900); }
.settings-nav > button:hover { background: var(--brand-primary-soft); }
.settings-nav > button.active { background: var(--brand-primary-soft); }
.security-icon { color: var(--brand-primary); background: var(--brand-primary-soft); }
.device-icon { color: var(--brand-primary); background: var(--brand-primary-soft); }
.profile-form :deep(.el-input__wrapper.is-focus), .profile-form :deep(.el-input__wrapper:focus-within), .profile-form :deep(.el-textarea__inner:focus) { border-color: var(--blue-400); box-shadow: 0 0 0 2px rgb(255 167 167 / 24%), inset 0 1px 0 rgb(255 255 255 / 90%), 0 3px 8px rgb(210 75 75 / 12%); }
</style>
