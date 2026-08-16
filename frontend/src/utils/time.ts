const CHINA_TIME_ZONE = 'Asia/Shanghai'

function normalizeBeijingInput(value: string): string {
  // Database DateTime values are stored as UTC. Some legacy API responses omit
  // the offset, so attach UTC explicitly before formatting in Asia/Shanghai.
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
    ? value
    : `${value.replace(' ', 'T')}Z`
}

export function formatBeijingTime(value: string | null | undefined, options: Intl.DateTimeFormatOptions = {}): string {
  if (!value) return '--'
  const date = new Date(normalizeBeijingInput(value))
  if (Number.isNaN(date.getTime())) return '--'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: CHINA_TIME_ZONE,
    hourCycle: 'h23',
    ...options,
  }).format(date)
}

export function formatBeijingDate(value: string | null | undefined): string {
  return formatBeijingTime(value, { year: 'numeric', month: '2-digit', day: '2-digit' })
}

export function formatBeijingDateTime(value: string | null | undefined): string {
  return formatBeijingTime(value, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

export function beijingTimestamp(value: string): number {
  return new Date(normalizeBeijingInput(value)).getTime()
}

function beijingParts(value: Date): Record<string, string> {
  return Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: CHINA_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(value).map((item) => [item.type, item.value]))
}

export function beijingDateTimeLocalValue(value: Date): string {
  const parts = beijingParts(value)
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

export function beijingLocalToUtcIso(value: string): string | null {
  const date = new Date(`${value}+08:00`)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export function beijingToday(): string {
  const parts = beijingParts(new Date())
  return `${parts.year}-${parts.month}-${parts.day}`
}
