import { useEffect, useMemo, useState } from 'react'
import { fetchHealth, submitProof } from './api.js'
import { parseTerm } from './term.js'
import TraceTable from './components/TraceTable.jsx'

const STEP_TYPES = [
  { value: 'push', label: '压入作用域' },
  { value: 'pop', label: '弹出作用域' },
  { value: 'eq', label: '声明相等' },
  { value: 'neq', label: '声明不等' },
  { value: 'claim', label: '声称' },
]

const PRESETS = {
  congruence: {
    audit_id: 'demo-congruence',
    constants: 'a, b, c, d',
    functions: 'f:1\ng:2',
    steps: [
      { type: 'eq', left: 'a', right: 'b' },
      { type: 'eq', left: 'c', right: 'd' },
      { type: 'claim', left: 'f(a)', right: 'f(b)' },
      { type: 'claim', left: 'g(a,c)', right: 'g(b,d)' },
    ],
  },
  expired: {
    audit_id: 'demo-expired-scope',
    constants: 'a, b',
    functions: '',
    steps: [
      { type: 'push', left: '', right: '' },
      { type: 'eq', left: 'a', right: 'b' },
      { type: 'claim', left: 'a', right: 'b' },
      { type: 'pop', left: '', right: '' },
      { type: 'claim', left: 'a', right: 'b' },
    ],
  },
  rollback: {
    audit_id: 'demo-conflict-rollback',
    constants: 'a, b, c',
    functions: '',
    steps: [
      { type: 'neq', left: 'a', right: 'b' },
      { type: 'push', left: '', right: '' },
      { type: 'eq', left: 'a', right: 'c' },
      { type: 'eq', left: 'c', right: 'b' },
      { type: 'claim', left: '', right: '' },
      { type: 'pop', left: '', right: '' },
      { type: 'claim', left: 'a', right: 'b' },
    ],
  },
  sameLevel: {
    audit_id: 'demo-same-level-conflict',
    constants: 'a, b',
    functions: '',
    steps: [
      { type: 'eq', left: 'a', right: 'b' },
      { type: 'neq', left: 'a', right: 'b' },
    ],
  },
  unknown: {
    audit_id: 'demo-unknown-symbol',
    constants: 'a, b',
    functions: 'f:1',
    steps: [{ type: 'eq', left: 'f(a)', right: 'f(ghost)' }],
  },
}

function emptyStep() {
  return { type: 'eq', left: '', right: '' }
}

function buildSignature(constantsText, functionsText) {
  const constants = constantsText
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  const functions = {}
  for (const line of functionsText.split('\n')) {
    const s = line.trim()
    if (!s) continue
    const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*[:：]\s*(\d+)$/.exec(s)
    if (!m) {
      throw new Error(`函数声明格式错误：“${s}”，应为 名称:元数，例如 f:1`)
    }
    functions[m[1]] = Number(m[2])
  }
  return { constants, functions }
}

function buildPayload(auditId, signature, steps) {
  const out = []
  for (let i = 0; i < steps.length; i += 1) {
    const s = steps[i]
    if (s.type === 'push' || s.type === 'pop') {
      out.push({ type: s.type })
      continue
    }
    const hasL = s.left.trim() !== ''
    const hasR = s.right.trim() !== ''
    if (s.type === 'claim' && !hasL && !hasR) {
      out.push({ type: 'claim' })
      continue
    }
    if (!hasL || !hasR) {
      throw new Error(`第 ${i} 步缺少项：${s.type} 需要两个项（声称矛盾则两项都留空）`)
    }
    let left
    let right
    try {
      left = parseTerm(s.left)
    } catch (e) {
      throw new Error(`第 ${i} 步左项：${e.message}`)
    }
    try {
      right = parseTerm(s.right)
    } catch (e) {
      throw new Error(`第 ${i} 步右项：${e.message}`)
    }
    out.push({ type: s.type, left, right })
  }
  return { audit_id: auditId.trim(), signature, steps: out }
}

function VerdictBanner({ result }) {
  if (!result) return null
  const { verdict, accepted, failure_step: fail, error, replay } = result
  const cls = accepted
    ? verdict === 'contradiction'
      ? 'verdict-contradiction'
      : 'verdict-valid'
    : 'verdict-invalid'
  const text = accepted
    ? verdict === 'contradiction'
      ? '裁决：矛盾成立（轨迹结束时仍存在矛盾）'
      : '裁决：证明有效'
    : '裁决：证明不成立'
  return (
    <div className={`verdict ${cls}`}>
      <div className="verdict-head">
        <strong>{text}</strong>
        {replay?.replayed && <span className="replay-tag">重放冻结结果</span>}
      </div>
      {!accepted && (
        <div className="verdict-detail">
          失败位置：<code>{error ? result.error_position : `steps[${fail}]`}</code>
          <div>{error}</div>
        </div>
      )}
      {accepted && verdict === 'contradiction' && (
        <div className="verdict-detail">当前作用域内存在未消解的不等式与等式冲突。</div>
      )}
    </div>
  )
}

export default function App() {
  const [auditId, setAuditId] = useState('audit-001')
  const [constantsText, setConstantsText] = useState('a, b, c, d')
  const [functionsText, setFunctionsText] = useState('f:1\ng:2')
  const [steps, setSteps] = useState(() => [
    { type: 'eq', left: 'a', right: 'b' },
    { type: 'claim', left: 'f(a)', right: 'f(b)' },
  ])
  const [result, setResult] = useState(null)
  const [clientError, setClientError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [health, setHealth] = useState('checking')

  useEffect(() => {
    let alive = true
    const ping = async () => {
      try {
        const r = await fetchHealth()
        if (alive) setHealth(r.ok && r.body?.status === 'ok' ? 'up' : 'down')
      } catch {
        if (alive) setHealth('down')
      }
    }
    ping()
    const t = setInterval(ping, 5000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const stepCount = steps.length

  const updateStep = (i, patch) => {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))
  }
  const addStep = () => setSteps((prev) => (prev.length >= 180 ? prev : [...prev, emptyStep()]))
  const removeStep = (i) => setSteps((prev) => prev.filter((_, idx) => idx !== i))

  const loadPreset = (key) => {
    const p = PRESETS[key]
    setAuditId(p.audit_id)
    setConstantsText(p.constants)
    setFunctionsText(p.functions)
    setSteps(p.steps.map((s) => ({ ...s, left: s.left || '', right: s.right || '' })))
    setResult(null)
    setClientError('')
  }

  const handleSubmit = async () => {
    setClientError('')
    setResult(null)
    if (!auditId.trim()) {
      setClientError('审计标识不能为空')
      return
    }
    let payload
    try {
      const signature = buildSignature(constantsText, functionsText)
      payload = buildPayload(auditId, signature, steps)
    } catch (e) {
      setClientError(e.message)
      return
    }
    setSubmitting(true)
    try {
      const r = await submitProof(payload)
      if (r.body) {
        setResult(r.body)
        if (!r.ok && r.status !== 409) setClientError(r.body?.error || `请求失败（HTTP ${r.status}）`)
      } else {
        setClientError(`服务端返回了无法解析的内容（HTTP ${r.status}）`)
      }
    } catch (e) {
      setClientError(`请求失败：${e.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const verdictSteps = result?.steps || []

  const presets = useMemo(
    () => [
      ['congruence', '有效等式 + 同余'],
      ['expired', '失效作用域'],
      ['rollback', '冲突与回退'],
      ['sameLevel', '同层冲突'],
      ['unknown', '未知符号'],
    ],
    [],
  )

  return (
    <div className="page">
      <header className="topbar">
        <h1>深空载荷同余闭包审查台</h1>
        <span className={`health health-${health}`}>
          后端：{health === 'up' ? '● 在线' : health === 'checking' ? '◌ 检查中' : '○ 离线'}
        </span>
      </header>

      <section className="panel">
        <h2>页面录入</h2>
        <div className="form-grid">
          <label className="field field-audit">
            <span>稳定审计标识</span>
            <input value={auditId} onChange={(e) => setAuditId(e.target.value)} />
          </label>
          <div className="presets">
            <span>示例：</span>
            {presets.map(([key, label]) => (
              <button key={key} type="button" className="preset-btn" onClick={() => loadPreset(key)}>
                {label}
              </button>
            ))}
          </div>
          <label className="field">
            <span>有限个常量（逗号或空白分隔）</span>
            <input value={constantsText} onChange={(e) => setConstantsText(e.target.value)} />
          </label>
          <label className="field">
            <span>定元函数（每行 名称:元数）</span>
            <textarea rows={3} value={functionsText} onChange={(e) => setFunctionsText(e.target.value)} />
          </label>
        </div>

        <div className="steps-head">
          <h3>证明轨迹（{stepCount}/180 步，只能压入/弹出作用域、声明相等/不等、声称相等或矛盾）</h3>
          <button type="button" className="add-btn" onClick={addStep} disabled={stepCount >= 180}>
            + 增加一步
          </button>
        </div>
        <div className="step-rows">
          {steps.map((s, i) => {
            const needsTerms = s.type === 'eq' || s.type === 'neq' || s.type === 'claim'
            const claimContradiction = s.type === 'claim' && s.left.trim() === '' && s.right.trim() === ''
            return (
              <div className="step-row" key={i}>
                <span className="step-idx">{i}</span>
                <select value={s.type} onChange={(e) => updateStep(i, { type: e.target.value })}>
                  {STEP_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
                {needsTerms ? (
                  <>
                    <input
                      className="term-input"
                      placeholder={s.type === 'claim' ? '左项（矛盾声称留空）' : '左项，如 a 或 f(a,b)'}
                      value={s.left}
                      onChange={(e) => updateStep(i, { left: e.target.value })}
                    />
                    <span className="step-rel">{s.type === 'neq' ? '≠' : '='}</span>
                    <input
                      className="term-input"
                      placeholder={s.type === 'claim' ? '右项（矛盾声称留空）' : '右项'}
                      value={s.right}
                      onChange={(e) => updateStep(i, { right: e.target.value })}
                    />
                    {claimContradiction && <span className="hint">将声称“已出现矛盾”</span>}
                  </>
                ) : (
                  <span className="hint">{s.type === 'push' ? '开启新的局部配置作用域' : '回滚当前作用域内全部事实'}</span>
                )}
                <button type="button" className="del-btn" onClick={() => removeStep(i)}>删除</button>
              </div>
            )
          })}
          {steps.length === 0 && <div className="muted">轨迹为空。点击“增加一步”开始录入。</div>}
        </div>

        <div className="submit-bar">
          <button type="button" className="submit-btn" onClick={handleSubmit} disabled={submitting || health === 'down'}>
            {submitting ? '提交中…' : '提交审查'}
          </button>
          {clientError && <span className="client-error">{clientError}</span>}
        </div>
      </section>

      {result && (
        <section className="panel">
          <h2>当前裁决</h2>
          <VerdictBanner result={result} />
          <div className="meta-line">
            <span>审计标识：<code>{result.audit_id}</code></span>
            <span>结束时作用域深度：{result.scope_depth}</span>
            <span>
              重放：{result.replay?.replayed ? '是（同标识同载荷，返回冻结结果）' : '否（首次提交）'}
            </span>
          </div>
          {result.failure_step !== null && result.failure_step !== undefined && (
            <div className="failure-position">
              首条不成立的位置：<code>steps[{result.failure_step}]</code>，其后旧证据已清除，不再执行。
            </div>
          )}
          <h3>轨迹回放</h3>
          <TraceTable steps={verdictSteps} />
        </section>
      )}
    </div>
  )
}
