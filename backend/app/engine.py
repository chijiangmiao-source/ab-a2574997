"""Rollback congruence closure with scoped equality/inequality assumptions.

Semantics
---------
* ``push`` opens a scope, ``pop`` rolls back *every* fact introduced inside it
  (union edges, congruence merges and disequality declarations) via an undo
  log. Interned term nodes from inner scopes are inert once their facts are
  gone, so keeping the nodes does not leak inner knowledge.
* Equalities are maintained by a union/find structure (union by size, no path
  compression so every parent edge can be undone). Each edge remembers why it
  was created: a direct ``eq`` declaration or a congruence propagation between
  two applications of the same function whose arguments are pairwise equal.
* Disequalities are records ``u != v`` tagged with the step and scope depth.
  A contradiction is present whenever the endpoints of any disequality lie in
  the same equivalence class.
* A direct ``eq`` against a disequality introduced at the *same* scope depth is
  a same-level conflict (proof error). A direct conflict with an outer scope,
  or a conflict reached through congruence propagation, creates a claimable
  contradiction that disappears when the responsible scope is popped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

MAX_STEPS = 180
MAX_SCOPE_DEPTH = 180
MAX_TERM_NODES = 2000


class ProofError(Exception):
    def __init__(self, code: str, message: str, field: str = "step"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


@dataclass
class DeclReason:
    step: int
    depth: int
    u: int
    v: int
    kind: str = "decl"


@dataclass
class CongReason:
    step: int
    depth: int
    u: int  # first application node
    v: int  # second application node
    trigger: str = "declaration"  # or "closure": new term entered the graph
    kind: str = "cong"


@dataclass
class DiseqRecord:
    u: int
    v: int
    step: int
    depth: int


class TermInterner:
    """Maps the shared term structure to dense node ids."""

    def __init__(self, constants: list[str], functions: dict[str, int]):
        self.constants = set(constants)
        self.functions = dict(functions)
        self.name_of: list[str] = []
        self.args_of: list[Optional[tuple[int, ...]]] = []
        self.const_id: dict[str, int] = {}
        self.app_id: dict[tuple[Any, ...], int] = {}
        for name in constants:
            self._new_node(name, None)
            self.const_id[name] = len(self.name_of) - 1

    def _new_node(self, name: str, args: Optional[tuple[int, ...]]) -> int:
        self.name_of.append(name)
        self.args_of.append(args)
        return len(self.name_of) - 1

    def is_app(self, node: int) -> bool:
        return self.args_of[node] is not None

    def intern(self, term: Any) -> int:
        if isinstance(term, str):
            node = self.const_id.get(term)
            if node is None:
                if term in self.functions:
                    raise ProofError(
                        "unknown_symbol",
                        f"未知符号：常量 “{term}” 未在签名中声明（它是函数名，不能作零元项）",
                        field="term",
                    )
                raise ProofError(
                    "unknown_symbol",
                    f"未知符号：常量 “{term}” 未在签名中声明",
                    field="term",
                )
            return node
        if isinstance(term, list) and len(term) >= 1 and isinstance(term[0], str):
            fn = term[0]
            if fn not in self.functions:
                if fn in self.constants:
                    raise ProofError(
                        "unknown_symbol",
                        f"未知符号：“{fn}” 是常量，不能作为函数应用",
                        field="term",
                    )
                raise ProofError(
                    "unknown_symbol",
                    f"未知符号：函数 “{fn}” 未在签名中声明",
                    field="term",
                )
            arity = self.functions[fn]
            if len(term) - 1 != arity:
                raise ProofError(
                    "arity_mismatch",
                    f"元数不符：函数 “{fn}” 需要 {arity} 个实参，实际给出 {len(term) - 1} 个",
                    field="term",
                )
            children = tuple(self.intern(arg) for arg in term[1:])
            key = (fn, children)
            node = self.app_id.get(key)
            if node is None:
                node = self._new_node(fn, children)
                self.app_id[key] = node
            return node
        raise ProofError(
            "malformed_term",
            "项的格式非法：应为常量名（字符串）或 [函数名, 实参…] 形式的列表",
            field="term",
        )

    def render(self, node: int) -> Any:
        args = self.args_of[node]
        if args is None:
            return self.name_of[node]
        return [self.name_of[node], *(self.render(a) for a in args)]


class ProofEngine:
    def __init__(self, signature: dict[str, Any]):
        constants = list(signature.get("constants", []))
        functions = dict(signature.get("functions", {}))
        self._validate_signature(constants, functions)
        self.terms = TermInterner(constants, functions)

        n = len(self.terms.name_of)  # constants pre-interned
        self.parent: list[int] = list(range(n))
        self.size: list[int] = [1] * n
        self.reason: list[Optional[Any]] = [None] * n
        # scopes[0] is the base frame; it is never popped.
        self.scopes: list[list[tuple[Any, ...]]] = [[]]
        self.diseqs: list[DiseqRecord] = []
        self.depth = 0
        # Congruence pairs propagated while interning terms of the current
        # step (a new term entering the graph must immediately close against
        # all existing equalities).
        self._closure_pairs: list[tuple[int, int]] = []

    # ---- signature -------------------------------------------------------
    @staticmethod
    def _validate_signature(constants: list[str], functions: dict[str, int]) -> None:
        if len(set(constants)) != len(constants):
            dup = {c for c in constants if constants.count(c) > 1}
            raise ProofError(
                "invalid_signature",
                f"签名非法：常量重复声明：{sorted(dup)}",
                field="signature.constants",
            )
        for name, arity in functions.items():
            if not isinstance(arity, int) or arity < 0:
                raise ProofError(
                    "invalid_signature",
                    f"签名非法：函数 “{name}” 的元数必须是非负整数",
                    field="signature.functions",
                )
            if name in constants:
                raise ProofError(
                    "invalid_signature",
                    f"签名非法：“{name}” 同时被声明为常量和函数",
                    field="signature",
                )

    # ---- undo log --------------------------------------------------------
    def _log(self, entry: tuple[Any, ...]) -> None:
        self.scopes[-1].append(entry)

    def intern(self, term: Any) -> int:
        """Intern a term, allocating tracked DSU state for new nodes.

        Every newly introduced application immediately participates in the
        congruence closure: if another application of the same function has
        pairwise-equivalent arguments, they are merged with a ``closure``
        reason. Propagated pairs are collected in ``self._closure_pairs``.
        """
        before = len(self.terms.name_of)
        node = self.terms.intern(term)
        for i in range(before, len(self.terms.name_of)):
            # Node created by the interner but missing DSU arrays (nested
            # applications allocate several nodes in one call).
            self.parent.append(i)
            self.size.append(1)
            self.reason.append(None)
        if len(self.terms.name_of) > MAX_TERM_NODES:
            raise ProofError(
                "term_limit",
                f"项节点数超过上限 {MAX_TERM_NODES}",
                field="term",
            )
        if len(self.terms.name_of) > before:
            self._closure_pairs.extend(self._congruence_fixpoint(-1, "closure"))
        return node

    # ---- union/find ------------------------------------------------------
    def find(self, node: int) -> int:
        # Deliberately no path compression: the parent edge carries the
        # justification and is restored verbatim on rollback.
        while self.parent[node] != node:
            node = self.parent[node]
        return node

    def _climb(self, node: int) -> tuple[list[int], list[int]]:
        nodes: list[int] = []
        edge_children: list[int] = []
        while True:
            nodes.append(node)
            if self.parent[node] == node:
                return nodes, edge_children
            edge_children.append(node)
            node = self.parent[node]

    def _union(self, a: int, b: int, reason: Any) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self._log(("parent", rb, self.parent[rb]))
        self._log(("reason", rb, self.reason[rb]))
        self._log(("size", ra, self.size[ra]))
        self.parent[rb] = ra
        self.reason[rb] = reason
        self.size[ra] += self.size[rb]
        return True

    def _congruence_fixpoint(self, step: int, trigger: str) -> list[tuple[int, int]]:
        """Merge same-f applications with pairwise-equivalent arguments."""
        pairs: list[tuple[int, int]] = []
        while True:
            groups: dict[tuple[Any, ...], list[int]] = {}
            for node, args in enumerate(self.terms.args_of):
                if args is None:
                    continue
                key = (self.terms.name_of[node], tuple(self.find(a) for a in args))
                groups.setdefault(key, []).append(node)
            merged_any = False
            for members in groups.values():
                leader = members[0]
                for other in members[1:]:
                    if self.find(leader) != self.find(other):
                        reason = CongReason(step, self.depth, leader, other, trigger)
                        if self._union(leader, other, reason):
                            pairs.append((leader, other))
                            merged_any = True
            if not merged_any:
                return pairs

    # ---- scopes ----------------------------------------------------------
    def push(self) -> None:
        if self.depth >= MAX_SCOPE_DEPTH:
            raise ProofError(
                "scope_overflow",
                f"超出作用域：嵌套深度不得超过 {MAX_SCOPE_DEPTH} 层",
                field="type",
            )
        self.scopes.append([])
        self.depth += 1

    def pop(self) -> None:
        if self.depth == 0:
            raise ProofError(
                "empty_stack_pop",
                "空栈弹出：当前已在最外层作用域，无法继续弹出",
                field="type",
            )
        frame = self.scopes.pop()
        for entry in reversed(frame):
            kind = entry[0]
            if kind == "parent":
                self.parent[entry[1]] = entry[2]
            elif kind == "reason":
                self.reason[entry[1]] = entry[2]
            elif kind == "size":
                self.size[entry[1]] = entry[2]
            elif kind == "diseq":
                self.diseqs.remove(entry[1])
            else:  # pragma: no cover - defensive
                raise AssertionError(f"unknown undo entry {kind}")
        self.depth -= 1
        # Some rolled-back congruence edges may rest entirely on equalities
        # that survive (e.g. the applications only entered the graph inside
        # the popped scope). Re-close against the facts still in force; edges
        # that depended on inner equalities simply do not reappear.
        self._congruence_fixpoint(-1, "closure")

    # ---- disequalities & contradictions ---------------------------------
    def _diseq_between(self, ra: int, rb: int) -> Optional[DiseqRecord]:
        for rec in self.diseqs:
            cu, cv = self.find(rec.u), self.find(rec.v)
            if cu == ra and cv == rb or cu == rb and cv == ra:
                return rec
        return None

    def _contradiction_witness(self) -> Optional[DiseqRecord]:
        for rec in self.diseqs:
            if self.find(rec.u) == self.find(rec.v):
                return rec
        return None

    def _add_diseq(self, rec: DiseqRecord) -> None:
        self._log(("diseq", rec))
        self.diseqs.append(rec)

    # ---- justifications --------------------------------------------------
    def _edge_chain(self, a: int, b: int) -> Optional[list[int]]:
        """Return edge-child ids on the path a -> b, or None if not equal."""
        na, ea = self._climb(a)
        nb, eb = self._climb(b)
        if na[-1] != nb[-1]:
            return None
        return ea + list(reversed(eb))

    def _justify_edge(self, child: int, memo: dict[tuple[int, int], Any]) -> dict[str, Any]:
        reason = self.reason[child]
        parent = self.parent[child]
        left_term = self.terms.render(child)
        right_term = self.terms.render(parent)
        if isinstance(reason, DeclReason):
            return {
                "rule": "declaration",
                "detail": (
                    f"第 {reason.step} 步在第 {reason.depth} 层直接声明 "
                    f"{self.terms.render(reason.u)} = {self.terms.render(reason.v)}"
                ),
                "children": [],
            }
        if isinstance(reason, CongReason):
            u_args = self.terms.args_of[reason.u]
            v_args = self.terms.args_of[reason.v]
            assert u_args is not None and v_args is not None
            fn = self.terms.name_of[reason.u]
            children: list[Any] = []
            for i, (xu, xv) in enumerate(zip(u_args, v_args)):
                children.append(
                    {
                        "rule": "argument_equality",
                        "detail": f"函数 {fn} 的第 {i + 1} 个实参等价",
                        "children": [self.justify(xu, xv, memo)],
                    }
                )
            return {
                "rule": "congruence",
                "detail": (
                    f"同余传播：{fn} 的实参逐项等价，故 "
                    f"{self.terms.render(reason.u)} = {self.terms.render(reason.v)}"
                    + (
                        f"（由第 {reason.step} 步的等式声明触发）"
                        if reason.trigger == "declaration"
                        else "（同余闭包依据当前生效的等式自动补算）"
                    )
                ),
                "children": children,
            }
        return {
            "rule": "edge",
            "detail": f"{left_term} 与 {right_term} 同属一个等价类",
            "children": [],
        }

    def justify(self, a: int, b: int, memo: Optional[dict[tuple[int, int], Any]] = None) -> dict[str, Any]:
        """Expandable proof tree for a = b: declarations + congruence steps."""
        if memo is None:
            memo = {}
        key = (min(a, b), max(a, b))
        cached = memo.get(key)
        if cached is not None:
            return cached
        if self.find(a) != self.find(b):
            return {
                "rule": "not_equal",
                "detail": f"{self.terms.render(a)} 与 {self.terms.render(b)} 当前不等价",
                "children": [],
            }
        # Reserve the slot to break any (defensive) recursive cycle.
        memo[key] = {"rule": "equivalence_class", "detail": "（同一等价类，见上文路径）", "children": []}
        chain = self._edge_chain(a, b)
        assert chain is not None
        if not chain:
            tree = {
                "rule": "reflexivity",
                "detail": f"{self.terms.render(a)} 与自身相等（自反性）",
                "children": [],
            }
        else:
            tree = {
                "rule": "equality_path",
                "detail": (
                    f"由 {self.terms.render(a)} 到 {self.terms.render(b)} 的等式链，"
                    f"共 {len(chain)} 条边；叶子为直接声明，congruence 节点可展开同余依据"
                ),
                "children": [self._justify_edge(c, memo) for c in chain],
            }
        memo[key] = tree
        return tree

    def justify_contradiction(self, rec: DiseqRecord) -> dict[str, Any]:
        return {
            "rule": "contradiction",
            "detail": (
                f"第 {rec.step} 步在第 {rec.depth} 层声明 "
                f"{self.terms.render(rec.u)} ≠ {self.terms.render(rec.v)}，"
                "但等式闭包当前将二者归入同一等价类"
            ),
            "children": [
                {
                    "rule": "disequality_declaration",
                    "detail": (
                        f"第 {rec.step} 步（第 {rec.depth} 层）声明的不等式 "
                        f"{self.terms.render(rec.u)} ≠ {self.terms.render(rec.v)}"
                    ),
                    "children": [],
                },
                self.justify(rec.u, rec.v),
            ],
        }

    # ---- step execution --------------------------------------------------
    def _render_pairs(self, pairs: list[tuple[int, int]]) -> list[dict[str, Any]]:
        return [
            {"left": self.terms.render(u), "right": self.terms.render(v)}
            for u, v in pairs
        ]

    def _terms_of(self, step: dict[str, Any], index: int) -> tuple[int, int]:
        left = step.get("left")
        right = step.get("right")
        if left is None or right is None:
            raise ProofError(
                "missing_term",
                f"第 {index} 步的 {('left' if left is None else 'right')} 缺失：该步骤需要两个项",
                field="left",
            )
        return self.intern(left), self.intern(right)

    def execute(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        if len(steps) > MAX_STEPS:
            raise ProofError(
                "too_many_steps",
                f"证明轨迹至多 {MAX_STEPS} 步，实际 {len(steps)} 步",
                field="steps",
            )
        results: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            stype = step.get("type")
            self._closure_pairs = []
            result: dict[str, Any] = {
                "index": index,
                "type": stype,
                "ok": False,
                "scope_depth": self.depth,
                "left": step.get("left"),
                "right": step.get("right"),
            }
            try:
                if stype == "push":
                    self.push()
                    result.update(ok=True, scope_depth=self.depth)
                elif stype == "pop":
                    self.pop()
                    result.update(ok=True, scope_depth=self.depth)
                elif stype == "eq":
                    a, b = self._terms_of(step, index)
                    closure_pairs = list(self._closure_pairs)
                    ra, rb = self.find(a), self.find(b)
                    if ra == rb:
                        result.update(
                            ok=True,
                            declared_equal=True,
                            justification=self.justify(a, b),
                            congruence_pairs=self._render_pairs(closure_pairs),
                        )
                    else:
                        rec = self._diseq_between(ra, rb)
                        if rec is not None and rec.depth == self.depth:
                            raise ProofError(
                                "same_level_conflict",
                                f"同层冲突：第 {rec.step} 步已在当前作用域（第 {self.depth} 层）"
                                f"声明 {self.terms.render(rec.u)} ≠ {self.terms.render(rec.v)}，"
                                "不能在同一层再声明二者相等",
                                field="left/right",
                            )
                        reason = DeclReason(index, self.depth, a, b)
                        self._union(a, b, reason)
                        decl_pairs = self._congruence_fixpoint(index, "declaration")
                        result.update(
                            ok=True,
                            declared_equal=True,
                            justification=self.justify(a, b),
                            congruence_pairs=self._render_pairs(closure_pairs + decl_pairs),
                        )
                elif stype == "neq":
                    a, b = self._terms_of(step, index)
                    ra, rb = self.find(a), self.find(b)
                    if ra == rb:
                        chain = self._edge_chain(a, b) or []
                        same_level_direct = any(
                            isinstance(self.reason[c], DeclReason)
                            and self.reason[c].depth == self.depth
                            for c in chain
                        )
                        if same_level_direct:
                            raise ProofError(
                                "same_level_conflict",
                                f"同层冲突：{self.terms.render(a)} 与 {self.terms.render(b)} "
                                f"已在当前作用域（第 {self.depth} 层）由直接声明归并为相等，"
                                "不能在同一层再声明不等",
                                field="left/right",
                            )
                        # Equality comes from an outer scope or purely from
                        # congruence propagation: record the contradiction.
                        rec = DiseqRecord(a, b, index, self.depth)
                        self._add_diseq(rec)
                        result.update(
                            ok=True,
                            declared_unequal=True,
                            justification=self.justify_contradiction(rec),
                            congruence_pairs=[],
                        )
                    else:
                        existing = self._diseq_between(ra, rb)
                        if existing is None:
                            rec = DiseqRecord(a, b, index, self.depth)
                            self._add_diseq(rec)
                        result.update(ok=True, declared_unequal=True)
                elif stype == "claim":
                    left = step.get("left")
                    right = step.get("right")
                    if left is None and right is None:
                        witness = self._contradiction_witness()
                        if witness is None:
                            raise ProofError(
                                "untenable_claim",
                                f"第 {index} 步声称已出现矛盾，但当前作用域内不存在矛盾",
                                field="type",
                            )
                        result.update(
                            ok=True,
                            justification=self.justify_contradiction(witness),
                        )
                    elif left is None or right is None:
                        raise ProofError(
                            "missing_term",
                            f"第 {index} 步声称格式非法：声称相等需同时给出两个项，"
                            "声称矛盾则两项均须省略",
                            field="left",
                        )
                    else:
                        a, b = self.intern(left), self.intern(right)
                        if self.find(a) != self.find(b):
                            raise ProofError(
                                "untenable_claim",
                                f"首条不成立的声称：第 {index} 步声称 "
                                f"{self.terms.render(a)} = {self.terms.render(b)}，"
                                "但二者在当前作用域内不等价",
                                field="left/right",
                            )
                        result.update(
                            ok=True,
                            justification=self.justify(a, b),
                            congruence_pairs=self._render_pairs(self._closure_pairs),
                        )
                else:
                    raise ProofError(
                        "unknown_step_type",
                        f"未知步骤类型：{stype!r}（只允许 push/pop/eq/neq/claim）",
                        field="type",
                    )
            except ProofError as exc:
                result.update(
                    ok=False,
                    error=exc.message,
                    error_position=f"steps[{index}].{exc.field}",
                )
                results.append(result)
                return {
                    "accepted": False,
                    "verdict": "invalid",
                    "failure_step": index,
                    "error": exc.message,
                    "error_code": exc.code,
                    "error_position": f"steps[{index}].{exc.field}",
                    "scope_depth": self.depth,
                    "steps": results,
                }
            results.append(result)

        witness = self._contradiction_witness()
        return {
            "accepted": True,
            "verdict": "contradiction" if witness is not None else "valid",
            "failure_step": None,
            "error": None,
            "error_code": None,
            "error_position": None,
            "scope_depth": self.depth,
            "steps": results,
        }


def validate_signature(signature: dict[str, Any]) -> None:
    constants = list(signature.get("constants", []))
    functions = dict(signature.get("functions", {}))
    ProofEngine._validate_signature(constants, functions)


def run_proof(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a full proof payload and return a response-ready dict."""
    signature = payload.get("signature") or {}
    try:
        validate_signature(signature)
        engine = ProofEngine(signature)
        outcome = engine.execute(list(payload.get("steps", [])))
    except ProofError as exc:
        return {
            "accepted": False,
            "verdict": "invalid",
            "failure_step": None,
            "error": exc.message,
            "error_code": exc.code,
            "error_position": exc.field,
            "scope_depth": 0,
            "steps": [],
        }
    outcome["audit_id"] = payload["audit_id"]
    return outcome
