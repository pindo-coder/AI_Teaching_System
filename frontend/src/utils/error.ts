import axios from 'axios'

export function getErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as {
      message?: string
      detail?: string
      errors?: Array<{ loc?: Array<string | number>; msg?: string }>
    } | undefined
    if (data?.errors?.length) {
      const details = data.errors.slice(0, 3).map((item) => {
        const location = (item.loc || []).filter((part) => part !== 'body')
        const rowIndex = location[0] === 'items' && typeof location[1] === 'number' ? Number(location[1]) + 1 : null
        const field = location.slice(rowIndex ? 2 : 0).join('.')
        return `${rowIndex ? `第${rowIndex}条 ` : ''}${field ? `${field}：` : ''}${item.msg || '格式无效'}`
      })
      return details.join('；')
    }
    return data?.message || data?.detail || fallback
  }
  return error instanceof Error ? error.message : fallback
}
