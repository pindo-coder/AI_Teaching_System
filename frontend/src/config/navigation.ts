import {
  Bell,
  Collection,
  DataAnalysis,
  Document,
  House,
  Management,
  Monitor,
  Reading,
  School,
  User,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import type { UserRole } from '@/types'

export interface NavigationItem {
  label: string
  description: string
  path: string
  icon: Component
  match?: string[]
}

const roleNavigation: Record<UserRole, NavigationItem[]> = {
  student: [
    { label: '今日学习', description: '待办、反馈与继续学习', path: '/', icon: House },
    { label: '课程学习', description: '教材专题与学习阶段', path: '/courses', icon: Reading, match: ['/courses'] },
    { label: '讨论共建', description: '课堂活动与观点交流', path: '/interaction', icon: User },
    { label: '笔记复习', description: '笔记、复习与知识沉淀', path: '/notes', icon: Document, match: ['/notes', '/reviews'] },
    { label: '学习任务', description: '教师布置与完成进度', path: '/assignments', icon: Bell },
  ],
  teacher: [
    { label: '教学工作台', description: '待备课、待发布与待审核', path: '/', icon: House },
    { label: '课程备课', description: '教材、证据与备课成果', path: '/lesson-prep', icon: Collection, match: ['/lesson-prep', '/courses'] },
    { label: '课堂教学', description: '任务发布与完成情况', path: '/assignments', icon: School },
    { label: '师生共建', description: '讨论、投稿与教师反馈', path: '/interaction', icon: User },
    { label: '资料动态', description: '候选资料与教材校准', path: '/material-review', icon: DataAnalysis, match: ['/material-review', '/knowledge', '/current-affairs'] },
  ],
  admin: [
    { label: '平台概览', description: '资料、教学与系统状态', path: '/', icon: House },
    { label: '教学管理', description: '教学班、教师与课程', path: '/classes', icon: Management, match: ['/classes', '/courses'] },
    { label: '资料动态', description: '来源发现、候选与发布确认', path: '/material-discovery', icon: DataAnalysis, match: ['/material-discovery', '/material-review'] },
    { label: '知识库治理', description: 'RAG 资料、索引与版本状态', path: '/knowledge', icon: Collection, match: ['/knowledge'] },
    { label: 'AI 运行中心', description: '模型调用、异常诊断与服务配置', path: '/ai-operations', icon: Monitor },
  ],
}

export function navigationForRole(role: UserRole | undefined): NavigationItem[] {
  return roleNavigation[role || 'student']
}
