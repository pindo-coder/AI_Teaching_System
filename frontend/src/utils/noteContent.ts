const ALLOWED_TAGS = new Set(['P', 'BR', 'HR', 'H2', 'H3', 'STRONG', 'B', 'EM', 'I', 'U', 'MARK', 'UL', 'OL', 'LI', 'SPAN'])

export function isRichNote(source: string): boolean {
  return /<(p|br|hr|h2|h3|strong|em|u|mark|ul|ol|li|span)\b/i.test(source)
}

export function plainTextToNoteHtml(source: string): string {
  const div = document.createElement('div')
  div.textContent = source
  return div.innerHTML
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${paragraph.replace(/\n/g, '<br>') || '<br>'}</p>`)
    .join('')
}

export function sanitizeNoteHtml(source: string): string {
  if (!isRichNote(source)) return plainTextToNoteHtml(source)
  const documentNode = new DOMParser().parseFromString(source, 'text/html')
  const clean = (node: Node): void => {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        const element = child as HTMLElement
        if (!ALLOWED_TAGS.has(element.tagName)) {
          clean(element)
          element.replaceWith(...element.childNodes)
          continue
        }
        const fontSize = element.style.fontSize
        const background = element.style.backgroundColor
        for (const attribute of [...element.attributes]) element.removeAttribute(attribute.name)
        if (element.tagName === 'SPAN' && /^(14|16|18|20|24)px$/.test(fontSize)) element.style.fontSize = fontSize
        if (element.tagName === 'MARK' && background) element.style.backgroundColor = background
      }
      clean(child)
    }
  }
  clean(documentNode.body)
  return documentNode.body.innerHTML
}

export function notePlainText(source: string): string {
  if (!isRichNote(source)) return source
  const documentNode = new DOMParser().parseFromString(source, 'text/html')
  return (documentNode.body.textContent || '').replace(/\s+/g, ' ').trim()
}
