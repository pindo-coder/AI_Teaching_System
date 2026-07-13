<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { getErrorMessage } from '@/utils/error'

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '', confirmPassword: '', role: 'student' as 'student' | 'teacher', identity_no: '' })
const validateConfirm = (_: unknown, value: string, callback: (error?: Error) => void) => {
  callback(value === form.password ? undefined : new Error('两次输入的密码不一致'))
}
const rules: FormRules = {
  username: [{ required: true, min: 3, max: 50, message: '用户名长度为 3～50 个字符', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: '密码至少 8 个字符', trigger: 'blur' }],
  confirmPassword: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
  role: [{ required: true, message: '请选择注册角色', trigger: 'change' }],
  identity_no: [{ required: true, min: 4, max: 32, pattern: /^[A-Za-z0-9_-]+$/, message: '请输入 4～32 位字母、数字或短横线编号', trigger: 'blur' }],
}
const router = useRouter()

async function submit() {
  if (!(await formRef.value?.validate())) return
  loading.value = true
  try {
    await authApi.register({ username: form.username, password: form.password, role: form.role, identity_no: form.identity_no })
    ElMessage.success('注册成功，请登录')
    await router.push('/login')
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '注册失败，请稍后重试'))
  } finally { loading.value = false }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-intro"><el-tag effect="dark" round>{{ form.role === 'teacher' ? '教师账号' : '学生账号' }}</el-tag><h1>创建你的<br />智能学习空间</h1><p>注册账号，开始课程化、阶段化的学习体验。</p></section>
    <el-card class="auth-card" shadow="never">
      <h2>创建账号</h2><p class="muted">请选择身份并填写对应的学号或工号</p>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="用户名" prop="username"><el-input v-model="form.username" size="large" /></el-form-item>
        <el-form-item label="注册角色" prop="role"><el-radio-group v-model="form.role"><el-radio-button value="student">学生</el-radio-button><el-radio-button value="teacher">教师</el-radio-button></el-radio-group></el-form-item>
        <el-form-item :label="form.role === 'teacher' ? '工号' : '学号'" prop="identity_no"><el-input v-model="form.identity_no" :placeholder="form.role === 'teacher' ? '请输入工号' : '请输入学号'" size="large" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" type="password" show-password size="large" /></el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword"><el-input v-model="form.confirmPassword" type="password" show-password size="large" /></el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="full-button" @click="submit">注册</el-button>
      </el-form>
      <p class="auth-switch">已有账号？<router-link to="/login">返回登录</router-link></p>
    </el-card>
  </main>
</template>
