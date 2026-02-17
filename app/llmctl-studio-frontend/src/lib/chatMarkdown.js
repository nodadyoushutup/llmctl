function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function sanitizeUrl(rawValue) {
  const raw = String(rawValue || '').trim()
  if (!raw) {
    return null
  }
  if (
    raw.startsWith('/') ||
    raw.startsWith('#') ||
    raw.startsWith('./') ||
    raw.startsWith('../')
  ) {
    return raw
  }
  try {
    const parsed = new URL(raw)
    if (['http:', 'https:', 'mailto:'].includes(parsed.protocol)) {
      return parsed.toString()
    }
  } catch {
    return null
  }
  return null
}

function renderInlineMarkdown(value) {
  if (!value) {
    return ''
  }

  const inlineCodeTokens = []
  let rendered = value.replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `@@INLINE_CODE_${inlineCodeTokens.length}@@`
    inlineCodeTokens.push(`<code>${code}</code>`)
    return token
  })

  rendered = rendered.replace(
    /\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g,
    (_, label, href, title) => {
      const safeHref = sanitizeUrl(href)
      const labelText = label || href
      if (!safeHref) {
        return labelText
      }
      const escapedHref = escapeHtml(safeHref)
      const escapedTitle = title ? ` title="${escapeHtml(title)}"` : ''
      return `<a href="${escapedHref}"${escapedTitle} target="_blank" rel="noopener noreferrer">${labelText}</a>`
    },
  )
  rendered = rendered.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  rendered = rendered.replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
  rendered = rendered.replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
  return rendered.replace(/@@INLINE_CODE_(\d+)@@/g, (_, index) => {
    const token = inlineCodeTokens[Number(index)]
    return token || ''
  })
}

function parseTableCells(line) {
  const normalized = String(line || '').trim()
  if (!normalized.includes('|')) {
    return []
  }
  const withoutEdgePipes = normalized.replace(/^\|/, '').replace(/\|$/, '')
  return withoutEdgePipes.split('|').map((item) => item.trim())
}

function tableAlignStyle(delimiterCell) {
  const token = String(delimiterCell || '').trim()
  if (token.startsWith(':') && token.endsWith(':')) {
    return 'center'
  }
  if (token.endsWith(':')) {
    return 'right'
  }
  return 'left'
}

export function renderChatMarkdown(rawValue) {
  const normalized = String(rawValue || '').replace(/\r\n/g, '\n')
  if (!normalized.trim()) {
    return ''
  }

  const escaped = escapeHtml(normalized)
  const codeBlockTokens = []
  let working = escaped.replace(
    /```([A-Za-z0-9_+-]*)[ \t]*\n?([\s\S]*?)```/g,
    (_, language, code) => {
      const token = `@@CODE_BLOCK_${codeBlockTokens.length}@@`
      const className = language ? ` class="language-${escapeHtml(language)}"` : ''
      const codeBody = code.endsWith('\n') ? code.slice(0, -1) : code
      codeBlockTokens.push(`<pre><code${className}>${codeBody}</code></pre>`)
      return token
    },
  )

  const blocks = working
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)

  const renderedBlocks = blocks.map((block) => {
    if (/^@@CODE_BLOCK_\d+@@$/.test(block)) {
      return block
    }
    if (/^([-*_]\s*){3,}$/.test(block)) {
      return '<hr />'
    }

    const heading = block.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      const text = renderInlineMarkdown(heading[2].trim())
      return `<h${level}>${text}</h${level}>`
    }

    const lines = block.split('\n')
    if (lines.length >= 2) {
      const headerCells = parseTableCells(lines[0])
      const delimiterCells = parseTableCells(lines[1])
      const isTable =
        headerCells.length > 0 &&
        headerCells.length === delimiterCells.length &&
        delimiterCells.every((cell) => /^:?-{3,}:?$/.test(cell))

      if (isTable) {
        const headerHtml = headerCells
          .map((cell, index) => {
            const align = tableAlignStyle(delimiterCells[index])
            return `<th style="text-align: ${align};">${renderInlineMarkdown(cell)}</th>`
          })
          .join('')
        const bodyRows = lines.slice(2).filter((line) => line.trim())
        const bodyHtml = bodyRows
          .map((row) => {
            const rowCells = parseTableCells(row)
            while (rowCells.length < headerCells.length) {
              rowCells.push('')
            }
            return (
              '<tr>' +
              headerCells
                .map((_, index) => {
                  const align = tableAlignStyle(delimiterCells[index])
                  const cellText = rowCells[index] || ''
                  return `<td style="text-align: ${align};">${renderInlineMarkdown(cellText)}</td>`
                })
                .join('') +
              '</tr>'
            )
          })
          .join('')
        return `<table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`
      }
    }

    if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
      const items = lines
        .map((line) => line.replace(/^\s*[-*]\s+/, ''))
        .map((line) => `<li>${renderInlineMarkdown(line)}</li>`)
        .join('')
      return `<ul>${items}</ul>`
    }

    if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
      const items = lines
        .map((line) => line.replace(/^\s*\d+\.\s+/, ''))
        .map((line) => `<li>${renderInlineMarkdown(line)}</li>`)
        .join('')
      return `<ol>${items}</ol>`
    }

    if (lines.every((line) => /^\s*>\s?/.test(line))) {
      const quote = lines
        .map((line) => line.replace(/^\s*>\s?/, ''))
        .map((line) => renderInlineMarkdown(line))
        .join('<br>')
      return `<blockquote>${quote}</blockquote>`
    }

    return `<p>${lines.map((line) => renderInlineMarkdown(line)).join('<br>')}</p>`
  })

  const html = renderedBlocks.join('\n')
  return html.replace(/@@CODE_BLOCK_(\d+)@@/g, (_, index) => {
    const token = codeBlockTokens[Number(index)]
    return token || ''
  })
}
