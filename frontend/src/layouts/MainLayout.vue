<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Menu } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import FloatingAiAssistant from '@/components/FloatingAiAssistant.vue'

const auth = useAuthStore()
const router = useRouter()
const mobileNavVisible = ref(false)
const navigationItems = computed(() => {
  const items = [
    { label: '课程中心', path: '/courses' },
    { label: '学习任务', path: '/assignments' },
    { label: '笔记空间', path: '/notes' },
    { label: '今日复习', path: '/reviews' },
    { label: '时政要点', path: '/current-affairs' },
    { label: '课堂互动', path: '/interaction' },
  ]
  if (auth.user?.role === 'teacher' || auth.user?.role === 'admin') {
    items.unshift({ label: '教学班', path: '/classes' })
  }
  if (auth.canManageKnowledge) {
    items.push({ label: '资料中心', path: '/knowledge' })
  }
  return items
})
const roleLabel = computed(() => ({ student: '学生', teacher: '教师', admin: '管理员' }[auth.user?.role || 'student']))

function logout() {
  auth.logout()
  router.push('/login')
}

function navigate(path: string) {
  mobileNavVisible.value = false
  router.push(path)
}
</script>

<template>
  <el-container class="app-layout">
    <el-container>
      <el-header class="topbar">
        <router-link to="/" class="brand" aria-label="返回首页"><span>思政智教</span><small>AI TEACHING</small></router-link>
        <nav class="topbar-links desktop-only" aria-label="主导航">
          <router-link v-for="item in navigationItems" :key="item.path" :to="item.path">{{ item.label }}</router-link>
        </nav>
        <el-button
          class="mobile-menu-trigger mobile-only"
          :icon="Menu"
          aria-label="打开主菜单"
          :aria-expanded="mobileNavVisible"
          @click="mobileNavVisible = true"
        >
          菜单
        </el-button>
        <el-dropdown class="desktop-user-menu">
          <span class="user-menu">{{ auth.user?.username }} · {{ roleLabel }}</span>
          <template #dropdown><el-dropdown-menu><el-dropdown-item @click="logout">退出登录</el-dropdown-item></el-dropdown-menu></template>
        </el-dropdown>
      </el-header>
      <el-main class="page"><router-view /></el-main>
      <FloatingAiAssistant />
      <el-drawer
        v-model="mobileNavVisible"
        title="功能导航"
        direction="rtl"
        size="min(86vw, 360px)"
        class="mobile-navigation-drawer"
      >
        <nav class="mobile-navigation" aria-label="移动端主导航">
          <button
            v-for="item in navigationItems"
            :key="item.path"
            type="button"
            :class="{ active: router.currentRoute.value.path === item.path }"
            @click="navigate(item.path)"
          >
            {{ item.label }}
          </button>
        </nav>
        <div class="mobile-user-panel">
          <span>{{ auth.user?.username }}</span>
          <small>{{ roleLabel }}</small>
          <el-button plain type="danger" @click="logout">退出登录</el-button>
        </div>
      </el-drawer>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-layout {
  min-width: 0;
  min-height: 100vh;
}

.topbar {
  position: sticky;
  z-index: 100;
  top: 0;
  display: flex;
  height: 64px;
  align-items: center;
  gap: var(--space-6);
  padding: 0 var(--page-padding);
  background: rgb(255 255 255 / 96%);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
}

.brand {
  display: grid;
  flex: none;
  color: var(--blue-800);
  text-decoration: none;
}

.brand span {
  font-size: 19px;
  font-weight: var(--fw-bold);
  line-height: 1.1;
}

.brand small {
  margin-top: 4px;
  color: var(--ink-400);
  font-size: var(--fs-meta);
  letter-spacing: 0.16em;
}

.topbar-links {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: flex-end;
  gap: clamp(12px, 1.5vw, 22px);
  margin-left: auto;
}

.topbar-links a {
  position: relative;
  padding: 22px 0 19px;
  color: var(--ink-600);
  font-size: var(--fs-body);
  text-decoration: none;
  white-space: nowrap;
}

.topbar-links a::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 2px;
  content: "";
  background: transparent;
}

.topbar-links a.router-link-active {
  color: var(--blue-600);
  font-weight: var(--fw-bold);
}

.topbar-links a.router-link-active::after {
  background: var(--blue-600);
}

.desktop-user-menu {
  flex: none;
}

.user-menu {
  color: var(--ink-600);
  cursor: pointer;
  font-size: var(--fs-aux);
  white-space: nowrap;
}

.page {
  min-width: 0;
  width: min(100%, calc(var(--page-max-width) + var(--page-padding) * 2));
  margin: 0 auto;
  padding: var(--space-8) var(--page-padding) 48px;
  overflow: visible;
}

.mobile-menu-trigger {
  margin-left: auto;
}

.mobile-navigation {
  display: grid;
  gap: var(--space-2);
}

.mobile-navigation button {
  width: 100%;
  padding: 13px 14px;
  color: var(--ink-600);
  background: transparent;
  border: 0;
  border-radius: var(--radius-input);
  cursor: pointer;
  text-align: left;
}

.mobile-navigation button:hover,
.mobile-navigation button.active {
  color: var(--blue-600);
  background: var(--blue-50);
  font-weight: var(--fw-medium);
}

.mobile-user-panel {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-8);
  padding-top: var(--space-6);
  border-top: 1px solid var(--line);
}

.mobile-user-panel span {
  color: var(--ink-900);
  font-weight: var(--fw-medium);
}

.mobile-user-panel small {
  color: var(--ink-400);
}

.mobile-user-panel .el-button {
  justify-self: start;
  margin-top: var(--space-2);
}

@media (max-width: 1023px) {
  .topbar {
    gap: var(--space-3);
  }

  .desktop-user-menu {
    display: none;
  }
}

@media (max-width: 767px) {
  .page {
    padding-top: var(--space-6);
  }
}
</style>
