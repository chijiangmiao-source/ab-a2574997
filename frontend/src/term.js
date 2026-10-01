// Parse a term from the text input.
// Accepts a bare constant ("a") or a JSON array application
// (["f","a",["g","b"]]). A parenthesised convenience spelling
// f(a, b) / f(a) is accepted too and converted to the JSON form.
export function parseTerm(text) {
  const s = text.trim()
  if (s === '') return null
  if (s.startsWith('[')) {
    return JSON.parse(s)
  }
  // convenience: f(a, b, g(c))
  const m = /^([A-Za-z_][A-Za-z0-9_]*)\((.*)\)$/s.exec(s)
  if (m) {
    const fn = m[1]
    const inside = m[2].trim()
    if (inside === '') return [fn]
    return [fn, ...splitArgs(inside).map(parseTerm)]
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(s)) {
    throw new Error(`无法解析项 “${text}”：应为常量名或 f(实参…) / ["f", ...] 形式`)
  }
  return s
}

function splitArgs(text) {
  const parts = []
  let depth = 0
  let cur = ''
  for (const ch of text) {
    if (ch === '(' || ch === '[') depth += 1
    if (ch === ')' || ch === ']') depth -= 1
    if (ch === ',' && depth === 0) {
      parts.push(cur.trim())
      cur = ''
    } else {
      cur += ch
    }
  }
  if (cur.trim() !== '') parts.push(cur.trim())
  return parts
}

export function renderTerm(term) {
  if (typeof term === 'string') return term
  if (Array.isArray(term)) return `${term[0]}(${term.slice(1).map(renderTerm).join(', ')})`
  return String(term)
}
