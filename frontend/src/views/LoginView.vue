<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'
import UiCard from '@/components/ui/UiCard.vue'
import UiHero from '@/components/ui/UiHero.vue'

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
  <main class="auth-page">
    <UiHero variant="auth" class="auth-intro-panel">
      <div class="auth-brand"><span>思政智教</span><small>AI TEACHING</small></div>
      <p class="auth-kicker">高校思政课 · 智能教学辅助平台</p>
      <h1>让教材学习<br />更聚焦、更可信</h1>
      <p class="auth-description">围绕教材专题、知识点和学习阶段提供 AI 辅助，并通过权威资料与原文引用保证回答有据可查。</p>
      <div class="auth-trust-list"><span>教材约束</span><span>权威资料</span><span>原文引用</span></div>
    </UiHero>
    <UiCard class="auth-card" :padded="false">
      <div class="auth-card-heading"><p class="eyebrow">欢迎回来</p><h2>登录学习空间</h2><p>继续你的专题学习、任务与个人笔记</p></div>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="用户名" prop="username"><el-input v-model="form.username" autocomplete="username" size="large" placeholder="请输入用户名" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" autocomplete="current-password" type="password" show-password size="large" placeholder="请输入密码" /></el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="full-button" @click="submit">登录</el-button>
      </el-form>
      <p class="auth-switch">还没有账号？<router-link to="/register">立即注册</router-link></p>
    </UiCard>
  </main>
</template>

<style scoped>
.auth-page {
  display: grid;
  width: min(100%, 1120px);
  min-height: 100vh;
  grid-template-columns: minmax(0, 1.25fr) minmax(340px, 0.75fr);
  align-items: center;
  gap: clamp(32px, 7vw, 88px);
  margin: 0 auto;
  padding: clamp(24px, 5vw, 64px);
  background: var(--bg-page);
}

.auth-intro-panel {
  min-height: 520px;
}

.auth-brand {
  display: grid;
  width: max-content;
  margin-bottom: 52px;
}

.auth-brand span {
  color: #fff;
  font-size: 22px;
  font-weight: var(--fw-bold);
}

.auth-brand small {
  margin-top: var(--space-1);
  color: rgb(255 255 255 / 72%);
  font-size: var(--fs-meta);
  letter-spacing: 0.18em;
}

.auth-kicker {
  margin: 0;
  color: rgb(255 255 255 / 78%);
  font-size: var(--fs-meta);
  font-weight: var(--fw-bold);
  letter-spacing: 0.1em;
}

.auth-intro-panel h1 {
  margin: var(--space-3) 0 var(--space-4);
  font-size: clamp(34px, 4vw, 46px);
  line-height: 1.25;
}

.auth-description {
  max-width: 560px;
  margin: 0;
  color: rgb(255 255 255 / 82%);
  font-size: 16px;
  line-height: 1.8;
}

.auth-trust-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-8);
}

.auth-trust-list span {
  padding: 7px 11px;
  color: rgb(255 255 255 / 86%);
  background: rgb(255 255 255 / 10%);
  border: 1px solid rgb(255 255 255 / 24%);
  border-radius: 999px;
  font-size: var(--fs-meta);
}

.auth-card {
  width: min(100%, 380px);
  justify-self: end;
  padding: 32px;
  box-shadow: var(--shadow-2);
}

.auth-card-heading {
  margin-bottom: var(--space-6);
}

.auth-card-heading p {
  margin: 0;
}

.auth-card-heading > p:last-child {
  color: var(--ink-600);
  line-height: 1.6;
}

.auth-card-heading h2 {
  margin: var(--space-1) 0 var(--space-2);
  font-size: var(--fs-section);
}

.full-button {
  width: 100%;
}

.auth-switch {
  margin: var(--space-6) 0 0;
  color: var(--ink-600);
  text-align: center;
}

@media (max-width: 767px) {
  .auth-page {
    width: 100%;
    min-height: 100vh;
    grid-template-columns: minmax(0, 1fr);
    align-content: center;
    gap: var(--space-4);
    padding: var(--space-4);
  }

  .auth-intro-panel {
    min-height: 0;
  }

  .auth-brand {
    margin-bottom: var(--space-6);
  }

  .auth-intro-panel h1 {
    margin-block: var(--space-2);
    font-size: 24px;
  }

  .auth-description {
    font-size: var(--fs-body);
    line-height: 1.65;
  }

  .auth-trust-list {
    margin-top: var(--space-4);
  }

  .auth-card {
    width: min(100%, 380px);
    justify-self: center;
    padding: var(--space-6);
    box-shadow: none;
  }
}
</style>
