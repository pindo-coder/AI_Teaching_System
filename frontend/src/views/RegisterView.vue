<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { getErrorMessage } from '@/utils/error'

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
  <main class="auth-page">
    <section class="auth-intro"><el-tag effect="dark" round>{{ form.role === 'teacher' ? '教师账号' : '学生账号' }}</el-tag><h1>创建你的<br />智能学习空间</h1><p>注册账号，开始课程化、阶段化的学习体验。</p></section>
    <el-card class="auth-card" shadow="never">
      <template v-if="!registered">
      <h2>创建账号</h2><p class="muted">请选择身份并填写对应的学号或工号</p>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="用户名" prop="username"><el-input v-model="form.username" size="large" /></el-form-item>
        <el-form-item label="注册角色" prop="role"><el-radio-group v-model="form.role"><el-radio-button value="student">学生</el-radio-button><el-radio-button value="teacher">教师</el-radio-button></el-radio-group></el-form-item>
        <el-form-item :label="form.role === 'teacher' ? '工号' : '学号'" prop="identity_no"><el-input v-model="form.identity_no" :placeholder="form.role === 'teacher' ? '请输入工号' : '请输入学号'" size="large" /></el-form-item>
        <el-form-item label="邮箱" prop="email"><el-input v-model="form.email" type="email" autocomplete="email" placeholder="用于验证和找回密码" size="large" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" /></el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword"><el-input v-model="form.confirmPassword" type="password" show-password size="large" /></el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="full-button" @click="submit">注册</el-button>
      </el-form>
      <p class="auth-switch">已有账号？<router-link to="/login">返回登录</router-link></p>
      </template>
      <template v-else>
        <p class="eyebrow">验证邮箱</p>
        <h2>请查收验证码邮件</h2>
        <p class="muted">验证码邮件已发送到 {{ form.email }}。输入邮件中的 6 位验证码完成验证后，才能登录学习空间。</p>
        <p class="muted">本地开发使用 console 邮件模式时，验证码会显示在后端终端日志中。</p>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="confirmEmail">
          <el-form-item label="验证码" prop="code"><el-input v-model="form.code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位数字" size="large" /></el-form-item>
          <el-button type="primary" size="large" class="full-button" :loading="verifying" @click="confirmEmail">确认验证</el-button>
        </el-form>
        <el-button text class="full-button secondary-button" @click="router.push('/login')">返回登录</el-button>
      </template>
    </el-card>
  </main>
</template>
