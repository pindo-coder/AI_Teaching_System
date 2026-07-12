function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function inlineFormat(value: string): string {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
}

/**
 * 将模型常见的 Markdown 文本转换为受限、已转义的教学文档 HTML。
 * 只允许标题、段落、加粗和列表，不直接信任模型返回的 HTML。
 */
export function renderTeachingDocument(source: string): string {
  const lines = source.replace(/```[\s\S]*?```/g, '').split('\n')
  const output: string[] = []
  let listType: 'ol' | 'ul' | null = null

  const closeList = () => {
    if (listType) output.push(`</${listType}>`)
    listType = null
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      closeList()
      continue
    }
    const heading = line.match(/^#{1,4}\s+(.+)$/)
    const numbered = line.match(/^\d+[.、]\s*(.+)$/)
    const bullet = line.match(/^[-•·]\s+(.+)$/)

    if (heading) {
      closeList()
      output.push(`<h3>${inlineFormat(heading[1])}</h3>`)
    } else if (numbered) {
      if (listType !== 'ol') { closeList(); listType = 'ol'; output.push('<ol>') }
      output.push(`<li>${inlineFormat(numbered[1])}</li>`)
    } else if (bullet) {
      if (listType !== 'ul') { closeList(); listType = 'ul'; output.push('<ul>') }
      output.push(`<li>${inlineFormat(bullet[1])}</li>`)
    } else {
      closeList()
      output.push(`<p>${inlineFormat(line)}</p>`)
    }
  }
  closeList()
  return output.join('')
}
