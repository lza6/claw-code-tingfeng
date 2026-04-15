export const OMX_GENERATED_AGENTS_MARKER = '<!-- omx:generated:agents-md -->'
const OMX_GENERATED_AGENTS_TITLE =
  '# oh-my-codex - Intelligent Multi-Agent Orchestration'
const AUTONOMY_DIRECTIVE_END_MARKER = '<!-- END AUTONOMY DIRECTIVE -->'

export function isOmxGeneratedAgentsMd(content: string): boolean {
  return (
    content.includes(OMX_GENERATED_AGENTS_MARKER) ||
    content.includes(OMX_GENERATED_AGENTS_TITLE)
  )
}

export function addGeneratedAgentsMarker(content: string): string {
  if (content.includes(OMX_GENERATED_AGENTS_MARKER)) return content

  const autonomyDirectiveEnd = content.indexOf(AUTONOMY_DIRECTIVE_END_MARKER)
  if (autonomyDirectiveEnd >= 0) {
    const insertAt = autonomyDirectiveEnd + AUTONOMY_DIRECTIVE_END_MARKER.length
    const hasImmediateNewline = content[insertAt] === '\n'
    const insertionPoint = hasImmediateNewline ? insertAt + 1 : insertAt
    return (
      content.slice(0, insertionPoint) +
      `${OMX_GENERATED_AGENTS_MARKER}\n` +
      content.slice(insertionPoint)
    )
  }

  const firstNewline = content.indexOf('\n')
  if (firstNewline === -1) {
    return `${content}\n${OMX_GENERATED_AGENTS_MARKER}\n`
  }

  return (
    content.slice(0, firstNewline + 1) +
    `${OMX_GENERATED_AGENTS_MARKER}\n` +
    content.slice(firstNewline + 1)
  )
}
