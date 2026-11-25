import type { NewsClassroomActivityType, NewsDebateSourceCitation, NewsItem } from '@/api/news'

const LESSON_PREP_KEY = 'news_handoff_lesson_prep_v1'
const CLASSROOM_DEBATE_KEY = 'news_handoff_classroom_debate_v1'
const HANDOFF_TTL_MS = 15 * 60 * 1000

export interface LessonPrepNewsHandoff {
  newsItem: NewsItem
  courseId: number
  chapterId: number
  teachingClassId: number | null
  teachingGoal: string
  relationReason: string
  createdAt: number
}

export interface ClassroomDebateHandoff {
  teachingClassId: number | null
  courseId: number
  chapterId: number
  activityType: NewsClassroomActivityType
  question: string
  options: string[]
  minutes: number
  teachingGuide: string[]
  textbookPosition: string
  sourceCitation: NewsDebateSourceCitation
  createdAt: number
}

function writePayload<T extends { createdAt: number }>(key: string, payload: Omit<T, 'createdAt'>): void {
  try {
    sessionStorage.setItem(key, JSON.stringify({ ...payload, createdAt: Date.now() }))
  } catch {
    // 隐私模式或存储受限时忽略，调用方仍可通过路由 query 回退
  }
}

function consumePayload<T extends { createdAt: number }>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    sessionStorage.removeItem(key)
    const parsed = JSON.parse(raw) as T
    if (!parsed || typeof parsed.createdAt !== 'number' || Date.now() - parsed.createdAt > HANDOFF_TTL_MS) {
      return null
    }
    return parsed
  } catch {
    sessionStorage.removeItem(key)
    return null
  }
}

export function saveLessonPrepNewsHandoff(payload: Omit<LessonPrepNewsHandoff, 'createdAt'>): void {
  writePayload<LessonPrepNewsHandoff>(LESSON_PREP_KEY, payload)
}

export function consumeLessonPrepNewsHandoff(): LessonPrepNewsHandoff | null {
  return consumePayload<LessonPrepNewsHandoff>(LESSON_PREP_KEY)
}

export function saveClassroomDebateHandoff(payload: Omit<ClassroomDebateHandoff, 'createdAt'>): void {
  writePayload<ClassroomDebateHandoff>(CLASSROOM_DEBATE_KEY, payload)
}

export function consumeClassroomDebateHandoff(): ClassroomDebateHandoff | null {
  return consumePayload<ClassroomDebateHandoff>(CLASSROOM_DEBATE_KEY)
}
