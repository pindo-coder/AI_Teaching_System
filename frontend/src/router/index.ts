import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition || { top: 0 }
  },
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue'), meta: { public: true } },
    { path: '/forgot-password', name: 'forgot-password', component: () => import('@/views/ForgotPasswordView.vue'), meta: { public: true } },
    { path: '/reset-password', name: 'reset-password', component: () => import('@/views/ResetPasswordView.vue'), meta: { public: true } },
    { path: '/verify-email', name: 'verify-email', component: () => import('@/views/VerifyEmailView.vue'), meta: { public: true } },
    { path: '/change-password', name: 'change-password', component: () => import('@/views/ChangePasswordView.vue') },
    { path: '/account', name: 'account', component: () => import('@/views/AccountView.vue'), meta: { roles: ['student', 'teacher'] } },
    { path: '/teacher-pending', name: 'teacher-pending', component: () => import('@/views/TeacherPendingView.vue') },
    {
      path: '/', component: () => import('@/layouts/MainLayout.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/WorkspaceHomeView.vue') },
        { path: 'lesson-prep', name: 'lesson-prep', component: () => import('@/views/LessonPrepWorkspaceView.vue'), meta: { roles: ['teacher', 'admin'] } },
        { path: 'material-review', name: 'material-review', component: () => import('@/views/MaterialReviewView.vue'), meta: { roles: ['teacher'] } },
        { path: 'material-discovery', name: 'material-discovery', component: () => import('@/views/MaterialDiscoveryView.vue'), meta: { roles: ['admin'] } },
        { path: 'ai-operations', name: 'ai-operations', component: () => import('@/views/AiOperationsView.vue'), meta: { roles: ['admin'] } },
        { path: 'admin/password-resets', name: 'admin-password-resets', component: () => import('@/views/AdminPasswordResetView.vue'), meta: { roles: ['admin'] } },
        { path: 'courses', name: 'courses', component: () => import('@/views/CourseListView.vue') },
        { path: 'courses/:id', name: 'course-detail', component: () => import('@/views/CourseDetailView.vue') },
        { path: 'current-affairs', name: 'current-affairs', component: () => import('@/views/CurrentAffairsView.vue') },
        { path: 'interaction', name: 'interaction', component: () => import('@/views/ClassroomInteractionView.vue') },
        { path: 'reviews', name: 'reviews', component: () => import('@/views/ReviewsView.vue') },
        { path: 'notes', name: 'notes', component: () => import('@/views/NotesView.vue') },
        { path: 'assignments', name: 'assignments', component: () => import('@/views/AssignmentsView.vue') },
        { path: 'classes', name: 'teaching-classes', component: () => import('@/views/TeachingClassesView.vue') },
        { path: 'knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeBaseView.vue'), meta: { roles: ['teacher', 'admin'] } },
        { path: 'knowledge/documents/:documentId/calibrate', name: 'document-calibration', component: () => import('@/views/DocumentCalibrationView.vue'), meta: { roles: ['admin'] } },
        {
          path: 'courses/:courseId/chapters/:chapterId/:stage(preview|review|exam)',
          name: 'learning-stage',
          component: () => import('@/views/LearningStageView.vue'),
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (auth.token && (!auth.user || !auth.sessionChecked)) {
    try {
      await auth.loadCurrentUser()
    } catch {
      auth.logout(false)
      if (!to.meta.public) return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  if (!to.meta.public && (!auth.isAuthenticated || !auth.user)) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (auth.user?.must_change_password && to.name !== 'change-password') return { name: 'change-password' }
  if (auth.user?.role === 'admin' && to.name === 'material-review') {
    return {
      name: 'material-discovery',
      query: { ...to.query, filter: to.query.filter || 'pending_review' },
      hash: to.hash || '#candidate-pool',
      replace: true,
    }
  }
  if (auth.user?.role === 'teacher' && auth.user.approval_status !== 'approved' && to.name !== 'teacher-pending') return { name: 'teacher-pending' }
  if (to.name === 'teacher-pending' && auth.user?.approval_status === 'approved') return { name: 'dashboard' }
  if (to.meta.public && auth.isAuthenticated && auth.user && to.name !== 'verify-email') return { name: 'dashboard' }
  if (to.meta.roles && (!auth.user || !to.meta.roles.includes(auth.user.role))) return { name: 'dashboard' }
})

const CHUNK_RELOAD_KEY = 'app_chunk_reload_at'
router.onError((error, to) => {
  const message = error instanceof Error ? error.message : String(error || '')
  if (!/Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk/i.test(message)) {
    return
  }
  const now = Date.now()
  const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || '0')
  if (now - last < 15_000) return
  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(now))
  window.location.assign(to?.fullPath || window.location.href)
})

export default router
