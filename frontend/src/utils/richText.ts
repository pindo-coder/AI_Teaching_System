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
  let orderedItemCount = 0
  let canContinueOrderedList = false

  const closeList = () => {
    if (listType) output.push(`</${listType}>`)
    listType = null
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      // 模型经常在编号项之间插入空行，甚至把每一项都写成 ``1.``。
      // 空行本身不结束列表；后续标题、段落或另一种列表会按各自分支关闭，
      // 这样连续编号会渲染在同一个 ol 中，既不会重置也不会产生额外间距。
      continue
    }
    const heading = line.match(/^#{1,4}\s+(.+)$/)
    const numbered = line.match(/^(?:\d+[.、)]|[（(]\d+[）)])\s*(.+)$/)
    const bullet = line.match(/^[-•·]\s+(.+)$/)

    if (heading) {
      closeList()
      orderedItemCount = 0
      canContinueOrderedList = false
      output.push(`<h3>${inlineFormat(heading[1])}</h3>`)
    } else if (numbered) {
      if (listType !== 'ol') {
        closeList()
        listType = 'ol'
        const start = canContinueOrderedList && orderedItemCount > 0
          ? ` start="${orderedItemCount + 1}"`
          : ''
        output.push(`<ol${start}>`)
      }
      output.push(`<li>${inlineFormat(numbered[1])}</li>`)
      orderedItemCount += 1
      canContinueOrderedList = false
    } else if (bullet) {
      if (listType !== 'ul') { closeList(); listType = 'ul'; output.push('<ul>') }
      output.push(`<li>${inlineFormat(bullet[1])}</li>`)
      orderedItemCount = 0
      canContinueOrderedList = false
    } else if (orderedItemCount > 0 && /^\**\s*提问意图\s*[：:]/.test(line)) {
      // 预习题常在每个编号题目后插入“提问意图”。它不是新列表，
      // 但为了排版会暂时结束 ol；下一题需要从上一个编号继续。
      closeList()
      output.push(`<p>${inlineFormat(line)}</p>`)
      canContinueOrderedList = true
    } else {
      closeList()
      orderedItemCount = 0
      canContinueOrderedList = false
      output.push(`<p>${inlineFormat(line)}</p>`)
    }
  }
  closeList()
  return output.join('')
}
