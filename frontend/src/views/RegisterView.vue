<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, Message, School, User } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { getErrorMessage } from '@/utils/error'
import BrandLockup from '@/components/ui/BrandLockup.vue'
import loginVisualImage from '@/assets/login-visual.jpg'
import loginRobotImage from '@/assets/login-robot.png'

const formRef = ref<FormInstance>()
const loading = ref(false)
const registered = ref(false)
const verifying = ref(false)
const form = reactive({ username: '', password: '', confirmPassword: '', role: 'student' as 'student' | 'teacher', identity_no: '', email: '', code: '' })
const validateConfirm = (_: unknown, value: string, callback: (error?: Error) => void) => {
  callback(value === form.password ? undefined : new Error('两次输入的密码不一致'))
}
const rules: FormRules = {
  username: [{ required: true, min: 3, max: 50, message: '用户名长度为 3～50 个字符', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: '密码至少 8 个字符', trigger: 'blur' }],
  confirmPassword: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
  role: [{ required: true, message: '请选择注册角色', trigger: 'change' }],
  identity_no: [{ required: true, min: 4, max: 32, pattern: /^[A-Za-z0-9_-]+$/, message: '请输入 4～32 位字母、数字或短横线编号', trigger: 'blur' }],
  email: [{ required: true, type: 'email', message: '请输入有效邮箱', trigger: 'blur' }],
  code: [{ required: true, len: 6, pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }],
}

async function confirmEmail() {
  if (!(await formRef.value?.validateField('code'))) return
  verifying.value = true
  try {
    await authApi.confirmEmailVerification(form.email, form.code)
    ElMessage.success('邮箱验证成功，现在可以登录')
    router.push('/login')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '验证码无效或已过期'))
  } finally { verifying.value = false }
}
const router = useRouter()

async function submit() {
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await authApi.register({ username: form.username, password: form.password, role: form.role, identity_no: form.identity_no, email: form.email })
    registered.value = true
    ElMessage.success('注册成功，验证码已发送')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '注册失败，请稍后重试'))
  } finally { loading.value = false }
}
</script>

<template>
  <main class="auth-page register-page">
    <section class="login-visual" aria-label="思政智教品牌介绍">
      <img class="login-visual-art" :src="loginVisualImage" alt="" aria-hidden="true" />
      <BrandLockup class="auth-branding" title="思政红芯" subtitle="思政智教 · 思政教学平台" tone="light" />
    </section>
    <section class="login-form-panel register-form-panel" aria-labelledby="register-title">
      <img class="login-robot" :src="loginRobotImage" alt="" aria-hidden="true" />
      <template v-if="!registered">
        <div class="login-form-heading register-form-heading">
          <h2 id="register-title">{{ form.role === 'teacher' ? '创建教师账号' : '创建学生账号' }}</h2>
          <p>填写您的详细信息，完成邮箱验证</p>
        </div>
        <el-form ref="formRef" class="login-form register-form" :model="form" :rules="rules" label-position="top">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item label="注册角色" prop="role">
            <el-radio-group v-model="form.role" class="register-role">
              <el-radio-button value="student">学生</el-radio-button>
              <el-radio-button value="teacher">教师</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item :label="form.role === 'teacher' ? '工号' : '学号'" prop="identity_no">
            <el-input v-model="form.identity_no" :placeholder="form.role === 'teacher' ? '请输入工号' : '请输入学号'" :prefix-icon="School" />
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input v-model="form.email" type="email" autocomplete="email" placeholder="用于验证和找回密码" :prefix-icon="Message" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" type="password" autocomplete="new-password" show-password placeholder="请输入至少 8 位密码" :prefix-icon="Lock" />
          </el-form-item>
          <el-form-item label="确认密码" prop="confirmPassword">
            <el-input v-model="form.confirmPassword" type="password" autocomplete="new-password" show-password placeholder="请再次输入密码" :prefix-icon="Lock" />
          </el-form-item>
          <el-button type="primary" :loading="loading" class="login-submit register-submit" @click="submit">创建账户</el-button>
        </el-form>
        <p class="login-register register-login-link">已有账号？<router-link to="/login">返回登录</router-link></p>
      </template>
      <template v-else>
        <div class="login-form-heading register-form-heading">
          <h2 id="register-title">验证您的邮箱</h2>
          <p>输入验证码，完成注册后即可登录</p>
        </div>
        <div class="register-stepper" aria-label="注册步骤"><span>1 填写账号</span><i aria-hidden="true">→</i><span class="is-current">2 验证邮箱</span></div>
        <p class="register-hint">验证码已发送到 <strong>{{ form.email }}</strong>，请输入邮件中的 6 位数字验证码。</p>
        <el-form ref="formRef" class="login-form register-form register-verify-form" :model="form" :rules="rules" label-position="top" @keyup.enter="confirmEmail">
          <el-form-item label="验证码" prop="code">
            <el-input v-model="form.code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位数字" />
          </el-form-item>
          <el-button type="primary" :loading="verifying" class="login-submit" @click="confirmEmail">确认验证</el-button>
        </el-form>
        <el-button text class="register-back-button" @click="router.push('/login')">返回登录</el-button>
      </template>
      <div class="login-underline" aria-hidden="true"><i></i><i></i></div>
    </section>
  </main>
</template>

<style scoped>
.register-page {
  display: grid;
  width: 100%;
  min-height: 100dvh;
  grid-template-columns: minmax(520px, 59.6%) minmax(400px, 1fr);
  gap: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background: #fff;
}

.register-page .login-visual {
  position: relative;
  display: flex;
  min-height: 100dvh;
  align-items: center;
  overflow: hidden;
  isolation: isolate;
  background: #f24a51;
}

.auth-branding {
  position: absolute;
  z-index: 2;
  top: clamp(24px, 5vh, 56px);
  left: clamp(24px, 5vw, 64px);
}

.register-page .login-visual-art {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
}

.register-form-panel {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-self: center;
  justify-content: flex-start;
  width: min(520px, calc(100% - 80px));
  max-height: 100dvh;
  padding: clamp(24px, 5vh, 52px) 0 24px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #e5dfe9 transparent;
}

.register-form-panel .login-robot {
  display: block;
  width: 112px;
  height: 148px;
  flex: none;
  align-self: center;
  margin: 0 auto 12px;
  object-fit: contain;
}

.register-form-heading {
  margin-bottom: 22px;
  text-align: center;
}

.register-form-heading h2 {
  margin: 0 0 12px;
  color: #140722;
  font-size: clamp(23px, 2vw, 28px);
  font-weight: 700;
  line-height: 1.3;
  white-space: normal;
}

.register-form-heading p {
  margin: 0;
  color: #7b7186;
  font-size: 14px;
  line-height: 1.7;
}

.register-form {
  width: 100%;
}

.register-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.register-form :deep(.el-form-item__label) {
  padding-bottom: 5px;
  color: #3f1e61;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.register-form :deep(.el-input__wrapper) {
  min-height: 40px;
  padding: 1px 12px;
  border: 1px solid #eae7ee;
  border-radius: 8px;
  box-shadow: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.register-form :deep(.el-input__wrapper:hover) {
  border-color: #c8bdcf;
}

.register-form :deep(.el-input__wrapper.is-focus) {
  border-color: #988ea6;
  box-shadow: 0 0 0 3px rgb(242 74 81 / 12%);
}

.register-form :deep(.el-input__inner) {
  color: #2b0f49;
  font-size: 14px;
}

.register-form :deep(.el-input__inner::placeholder) {
  color: #aaa2b1;
}

.register-form-panel .login-submit {
  width: 100%;
  height: 40px;
  color: #fff;
  background: #f24a51;
  border-color: #f24a51;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.register-form-panel .login-submit:hover,
.register-form-panel .login-submit:focus {
  color: #fff;
  background: #e83e47;
  border-color: #e83e47;
}

.register-form-panel .login-register {
  color: #7b7186;
  font-size: 15px;
  text-align: center;
}

.register-form-panel .login-register a {
  margin-left: 4px;
  color: #ff4a51;
  font-weight: 600;
}

.register-form-panel .login-underline {
  position: relative;
  width: 284px;
  height: 18px;
  flex: none;
  align-self: center;
  margin-top: auto;
}

.register-form-panel .login-underline i {
  position: absolute;
  right: 0;
  display: block;
  width: 284px;
  height: 1px;
  background: #ff4a51;
  transform: rotate(-5deg);
}

.register-form-panel .login-underline i:first-child {
  top: 8px;
}

.register-form-panel .login-underline i:last-child {
  top: 12px;
  right: 30px;
  width: 220px;
  transform: rotate(-7deg);
}

.register-form :deep(.el-input__prefix-inner > .el-icon) {
  color: #6d4d83;
  font-size: 17px;
}

.register-role {
  display: flex;
  width: 100%;
  gap: 8px;
}

.register-role :deep(.el-radio-button) {
  flex: 1;
}

.register-role :deep(.el-radio-button__inner) {
  width: 100%;
  padding: 10px 12px;
  color: #7b7186;
  background: #fff;
  border: 1px solid #eae7ee;
  border-radius: 8px !important;
  box-shadow: none !important;
  font-size: 14px;
}

.register-role :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-left: 1px solid #eae7ee;
}

.register-role :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  color: #fff;
  background: #f24a51;
  border-color: #f24a51;
}

.register-submit {
  margin-top: 2px;
}

.register-login-link {
  margin-top: 28px;
}

.register-stepper {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 22px;
  color: var(--ink-400);
  font-size: var(--fs-meta);
}

.register-stepper span {
  white-space: nowrap;
}

.register-stepper .is-current {
  color: #ff4a51;
  font-weight: var(--fw-bold);
}

.register-stepper i {
  color: #ffc9c9;
  font-style: normal;
}

.register-hint {
  margin: -4px 0 22px;
  color: #7b7186;
  font-size: 14px;
  line-height: 1.7;
}

.register-hint strong {
  color: #3f1e61;
  font-weight: 600;
}

.register-back-button {
  align-self: center;
  margin-top: 16px;
  color: #ff4a51;
}

@media (max-height: 820px) and (min-width: 901px) {
  .register-form-panel {
    padding-top: 14px;
    padding-bottom: 14px;
  }

  .register-form-panel .login-robot {
    width: 92px;
    height: 122px;
    margin-bottom: 8px;
  }

  .register-form-heading {
    margin-bottom: 14px;
  }

  .register-form-heading h2 {
    margin-bottom: 7px;
    font-size: 23px;
  }

  .register-form-heading p,
  .register-hint {
    font-size: 13px;
  }

  .register-form :deep(.el-form-item) {
    margin-bottom: 5px;
  }

  .register-form :deep(.el-form-item__label) {
    padding-bottom: 2px;
    line-height: 1.15;
  }

  .register-form :deep(.el-input__wrapper) {
    min-height: 36px;
  }

  .register-role :deep(.el-radio-button__inner) {
    padding-top: 6px;
    padding-bottom: 6px;
  }

  .register-login-link {
    margin-top: 8px;
  }

  .register-form-panel .login-underline {
    display: none;
  }
}

@media (max-width: 900px) {
  .register-page {
    grid-template-columns: minmax(0, 1fr);
    overflow: auto;
  }

  .register-page .login-visual {
    min-height: 380px;
  }

  .register-form-panel {
    width: min(520px, calc(100% - 64px));
    min-height: 0;
    padding: 42px 0 48px;
  }

  .register-form-panel .login-robot {
    width: 108px;
    height: 142px;
  }
}

@media (max-width: 767px) {
  .register-page {
    align-content: start;
  }

  .register-form-panel {
    width: min(520px, calc(100% - 40px));
    padding-right: 0;
    padding-left: 0;
  }

  .register-stepper {
    margin-bottom: 16px;
  }
}
</style>
