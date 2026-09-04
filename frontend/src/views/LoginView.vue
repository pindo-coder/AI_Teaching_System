<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'
import BrandLockup from '@/components/ui/BrandLockup.vue'
import loginVisualImage from '@/assets/login-visual.jpg'
import loginRobotImage from '@/assets/login-robot.png'

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

async function submit() {
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    await router.push(typeof route.query.redirect === 'string' ? route.query.redirect : '/')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '登录失败，请稍后重试'))
  } finally { loading.value = false }
}
</script>

<template>
  <main class="auth-page login-page">
    <section class="login-visual" aria-label="思政智教品牌介绍">
      <img class="login-visual-art" :src="loginVisualImage" alt="" aria-hidden="true" />
      <BrandLockup class="auth-branding" title="思政红芯" subtitle="思政智教 · 思政教学平台" tone="light" />
    </section>
    <section class="login-form-panel" aria-labelledby="login-title">
      <img class="login-robot" :src="loginRobotImage" alt="" aria-hidden="true" />
      <div class="login-form-heading">
        <h2 id="login-title">欢迎回来，思政红芯教育平台</h2>
        <p>欢迎回来，请填写您的详细信息</p>
      </div>
      <el-form ref="formRef" class="login-form" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" autocomplete="current-password" type="password" show-password placeholder="请输入密码" :prefix-icon="Lock" />
        </el-form-item>
        <router-link class="login-forgot" to="/forgot-password">忘记密码</router-link>
        <el-button type="primary" :loading="loading" class="login-submit" @click="submit">登录账户</el-button>
      </el-form>
      <p class="login-register">还没有账号？<router-link to="/register">免费注册</router-link></p>
      <div class="login-underline" aria-hidden="true"><i></i><i></i></div>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
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

.login-visual {
  position: relative;
  display: flex;
  min-height: 100dvh;
  align-items: center;
  overflow: hidden;
  isolation: isolate;
  color: #fff;
  background: #f24a51;
}

.auth-branding {
  position: absolute;
  z-index: 2;
  top: clamp(24px, 5vh, 56px);
  left: clamp(24px, 5vw, 64px);
}

.login-visual-art {
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
}

.login-form-panel {
  display: flex;
  width: min(440px, calc(100% - 80px));
  flex-direction: column;
  justify-content: center;
  justify-self: center;
  align-items: stretch;
  padding: 24px 0;
}

.login-robot {
  display: block;
  width: 132px;
  height: 176px;
  flex: none;
  align-self: center;
  margin: 0 auto 18px;
  object-fit: contain;
}

.login-form-heading {
  margin-bottom: 32px;
  text-align: center;
}

.login-form-heading h2 {
  margin: 0 0 12px;
  color: #140722;
  font-size: clamp(23px, 2vw, 28px);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.3;
  white-space: nowrap;
}

.login-form-heading p {
  margin: 0;
  color: #7b7186;
  font-size: 14px;
  line-height: 1.7;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 24px;
}

.login-form :deep(.el-form-item__label) {
  padding-bottom: 8px;
  color: #3f1e61;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.login-form :deep(.el-form-item__label::before) {
  color: #ff4a64;
}

.login-form :deep(.el-input__wrapper) {
  min-height: 40px;
  padding: 1px 12px;
  border: 1px solid #eae7ee;
  border-radius: 8px;
  box-shadow: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.login-form :deep(.el-input__wrapper:hover) {
  border-color: #c8bdcf;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  border-color: #988ea6;
  box-shadow: 0 0 0 3px rgb(242 74 81 / 12%);
}

.login-form :deep(.el-input__inner) {
  color: #2b0f49;
  font-size: 14px;
}

.login-form :deep(.el-input__inner::placeholder) {
  color: #aaa2b1;
}

.login-submit {
  width: 100%;
  height: 40px;
  margin-top: 4px;
  color: #fff;
  background: #f24a51;
  border-color: #f24a51;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.login-submit:hover,
.login-submit:focus {
  color: #fff;
  background: #e83e47;
  border-color: #e83e47;
}

.login-submit:active {
  background: #d9343d;
  border-color: #d9343d;
}

.login-forgot {
  display: block;
  margin: -7px 0 24px;
  color: #ff4a51;
  font-size: 13px;
}

.login-forgot:hover {
  color: #e83e47;
}

.login-register {
  margin: 46px 0 0;
  color: #7b7186;
  font-size: 15px;
  text-align: center;
}

.login-register a {
  margin-left: 4px;
  color: #ff4a51;
  font-weight: 600;
}

.login-register a:hover {
  color: #e83e47;
}

.login-underline {
  position: relative;
  width: 284px;
  height: 18px;
  align-self: center;
  margin-top: auto;
}

.login-underline i {
  position: absolute;
  right: 0;
  display: block;
  width: 284px;
  height: 1px;
  background: #ff4a51;
  transform: rotate(-5deg);
}

.login-underline i:first-child {
  top: 8px;
}

.login-underline i:last-child {
  top: 12px;
  right: 30px;
  width: 220px;
  transform: rotate(-7deg);
}

@media (max-width: 900px) {
  .auth-page {
    grid-template-columns: minmax(0, 1fr);
    overflow: auto;
  }

  .login-visual {
    min-height: 380px;
  }

  .login-form-panel {
    width: min(440px, calc(100% - 64px));
    min-height: 520px;
    padding: 56px 0;
  }

  .login-form-heading h2 { font-size: 25px; white-space: normal; }
}
</style>
