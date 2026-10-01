import JustificationTree from './JustificationTree.jsx'
import { renderTerm } from '../term.js'

const STEP_LABELS = {
  push: '压入作用域',
  pop: '弹出作用域',
  eq: '声明相等',
  neq: '声明不等',
  claim: '声称',
}

function Terms({ step }) {
  if (step.left === undefined || step.left === null) {
    return <span className="muted">—</span>
  }
  return (
    <>
      <code>{renderTerm(step.left)}</code>
      <span className="rel">{step.type === 'neq' ? '≠' : '='}</span>
      <code>{renderTerm(step.right)}</code>
    </>
  )
}

function StepRow({ step }) {
  return (
    <tr className={step.ok ? '' : 'step-failed'}>
      <td className="col-idx">{step.index}</td>
      <td>
        <span className={`badge badge-${step.type}`}>{STEP_LABELS[step.type]}</span>
      </td>
      <td className="col-depth">{step.scope_depth}</td>
      <td className="col-terms"><Terms step={step} /></td>
      <td className="col-status">
        {step.ok ? <span className="ok-pill">成立</span> : <span className="bad-pill">不成立</span>}
      </td>
      <td className="col-just">
        {step.justification ? (
          <details>
            <summary>展开依据</summary>
            <JustificationTree tree={step.justification} />
          </details>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
      <td className="col-cong">
        {(step.congruence_pairs || []).length > 0 ? (
          <details>
            <summary>{step.congruence_pairs.length} 对同余传播</summary>
            <ul className="cong-list">
              {step.congruence_pairs.map((p, i) => (
                <li key={i}>
                  <code>{renderTerm(p.left)}</code> = <code>{renderTerm(p.right)}</code>
                </li>
              ))}
            </ul>
          </details>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
      <td className="col-err">
        {step.error ? <div className="step-error">{step.error}</div> : <span className="muted">—</span>}
      </td>
    </tr>
  )
}

export default function TraceTable({ steps }) {
  return (
    <div className="table-wrap">
      <table className="trace-table">
        <thead>
          <tr>
            <th>#</th>
            <th>操作</th>
            <th>层</th>
            <th>两个项</th>
            <th>裁决</th>
            <th>声明 / 同余依据</th>
            <th>同余传播</th>
            <th>失败信息</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((step) => (
            <StepRow key={step.index} step={step} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
