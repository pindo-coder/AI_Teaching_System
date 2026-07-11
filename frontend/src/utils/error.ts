import axios from 'axios'

export function getErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { message?: string; detail?: string } | undefined
    return data?.message || data?.detail || fallback
  }
  return error instanceof Error ? error.message : fallback
}
