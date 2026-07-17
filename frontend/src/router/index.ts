import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue'), meta: { public: true } },
    { path: '/teacher-pending', name: 'teacher-pending', component: () => import('@/views/TeacherPendingView.vue') },
    {
      path: '/', component: () => import('@/layouts/MainLayout.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'courses', name: 'courses', component: () => import('@/views/CourseListView.vue') },
        { path: 'courses/:id', name: 'course-detail', component: () => import('@/views/CourseDetailView.vue') },
        { path: 'current-affairs', name: 'current-affairs', component: () => import('@/views/CurrentAffairsView.vue') },
        { path: 'interaction', name: 'interaction', component: () => import('@/views/ClassroomInteractionView.vue') },
        { path: 'reviews', name: 'reviews', component: () => import('@/views/ReviewsView.vue') },
        { path: 'notes', name: 'notes', component: () => import('@/views/NotesView.vue') },
        { path: 'assignments', name: 'assignments', component: () => import('@/views/AssignmentsView.vue') },
        { path: 'classes', name: 'teaching-classes', component: () => import('@/views/TeachingClassesView.vue') },
        { path: 'knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeBaseView.vue'), meta: { roles: ['teacher', 'admin'] } },
        { path: 'knowledge/documents/:documentId/calibrate', name: 'document-calibration', component: () => import('@/views/DocumentCalibrationView.vue'), meta: { roles: ['teacher', 'admin'] } },
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

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) return { name: 'login', query: { redirect: to.fullPath } }
  if (auth.user?.role === 'teacher' && auth.user.approval_status !== 'approved' && to.name !== 'teacher-pending') return { name: 'teacher-pending' }
  if (to.name === 'teacher-pending' && auth.user?.approval_status === 'approved') return { name: 'dashboard' }
  if (to.meta.public && auth.isAuthenticated) return { name: 'dashboard' }
  if (to.meta.roles && auth.user && !(to.meta.roles as string[]).includes(auth.user.role)) return { name: 'dashboard' }
})

export default router
