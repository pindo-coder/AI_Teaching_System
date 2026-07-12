function cleanPdfText(source: string): string {
  return source
    .replace(/\r/g, '')
    .replace(/([\u3400-\u9fff])\s+(?=[\u3400-\u9fff])/g, '$1')
    .replace(/\s+([，。；：！？、）》】])/g, '$1')
    .replace(/([《（【])\s+/g, '$1')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()
}

function splitLongParagraph(paragraph: string): string[] {
  if (paragraph.length <= 260) return [paragraph]
  const sentences = paragraph.match(/[^。！？；]+[。！？；]?/g) || [paragraph]
  const blocks: string[] = []
  let current = ''
  for (const sentence of sentences) {
    if (current && current.length + sentence.length > 240) {
      blocks.push(current.trim())
      current = ''
    }
    current += sentence
  }
  if (current.trim()) blocks.push(current.trim())
  return blocks
}

/** 清理 PDF 硬换行，并将教材长段落整理为适合屏幕阅读的句群。 */
export function formatTextbookParagraphs(source?: string | null): string[] {
  if (!source?.trim()) return []
  const cleaned = cleanPdfText(source)
  const originalParagraphs = cleaned
    .split(/\n\s*\n/)
    .map((item) => item.replace(/\n+/g, ' ').trim())
    .filter(Boolean)
  return originalParagraphs.flatMap(splitLongParagraph)
}

export function textbookPreview(source?: string | null, maxLength = 180): string {
  const text = formatTextbookParagraphs(source).join(' ')
  return text.length > maxLength ? `${text.slice(0, maxLength)}……` : text
}
