import { useState } from 'react'

const RULE_LABELS = {
  equality_path: '等式链',
  declaration: '直接声明',
  congruence: '同余传播',
  argument_equality: '实参等价',
  contradiction: '矛盾',
  disequality_declaration: '不等式声明',
  reflexivity: '自反性',
  not_equal: '不等价',
  equivalence_class: '同一等价类',
  edge: '等价类边',
}

function JustificationNode({ node, depth = 0 }) {
  const [open, setOpen] = useState(depth < 2)
  const children = node.children || []
  const hasChildren = children.length > 0
  return (
    <div className="just-node" style={{ marginLeft: depth === 0 ? 0 : 16 }}>
      <div className="just-line">
        {hasChildren ? (
          <button
            type="button"
            className="twisty"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? '▾' : '▸'}
          </button>
        ) : (
          <span className="twisty twisty-leaf">•</span>
        )}
        <span className={`just-rule rule-${node.rule}`}>
          {RULE_LABELS[node.rule] || node.rule}
        </span>
        <span className="just-detail">{node.detail}</span>
      </div>
      {open &&
        hasChildren &&
        children.map((child, i) => (
          <JustificationNode key={i} node={child} depth={depth + 1} />
        ))}
    </div>
  )
}

export default function JustificationTree({ tree }) {
  if (!tree) return <span className="muted">无</span>
  return <div className="just-tree"><JustificationNode node={tree} /></div>
}
