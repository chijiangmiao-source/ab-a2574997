"""Engine-level tests: valid equalities, expired scopes, conflict rollback."""
import pytest

from app.engine import MAX_STEPS, ProofEngine, ProofError, run_proof

BASE_SIG = {"constants": ["a", "b", "c", "d"], "functions": {"f": 1, "g": 2}}


def proof(audit_id="t", sig=None, steps=None):
    return {"audit_id": audit_id, "signature": sig or BASE_SIG, "steps": steps or []}


# ---------------------------------------------------------------- valid proofs
def test_reflexive_and_transitive_equality():
    r = run_proof(proof(steps=[
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "eq", "left": "b", "right": "c"},
        {"type": "claim", "left": "a", "right": "a"},
        {"type": "claim", "left": "a", "right": "c"},
    ]))
    assert r["accepted"] is True
    assert r["verdict"] == "valid"
    assert all(s["ok"] for s in r["steps"])


def test_congruence_merges_only_matching_applications():
    r = run_proof(proof(steps=[
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "claim", "left": ["f", "a"], "right": ["f", "b"]},
        {"type": "claim", "left": ["g", "a", "c"], "right": ["g", "b", "c"]},
    ]))
    assert r["verdict"] == "valid"
    # congruence was auto-closed when f(a) entered the graph
    assert r["steps"][1]["congruence_pairs"] == [
        {"left": ["f", "a"], "right": ["f", "b"]}
    ]


def test_different_functions_never_merge():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {"f": 1, "h": 1}},
        steps=[
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "claim", "left": ["f", "a"], "right": ["h", "b"]},
        ],
    ))
    assert r["accepted"] is False
    assert r["failure_step"] == 1
    assert r["error_code"] == "untenable_claim"


def test_arguments_must_be_pairwise_equivalent():
    r = run_proof(proof(steps=[
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "claim", "left": ["g", "a", "c"], "right": ["g", "b", "d"]},
    ]))
    assert r["verdict"] == "invalid"
    assert r["failure_step"] == 1


def test_nested_congruence_closes_in_fixpoint():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {"f": 1, "g": 1}},
        steps=[
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "claim", "left": ["g", ["f", "a"]], "right": ["g", ["f", "b"]]},
        ],
    ))
    assert r["verdict"] == "valid"
    tree = r["steps"][1]["justification"]
    # the justification tree is recursively expandable through two congruence hops
    serialized = str(tree)
    assert "congruence" in serialized
    assert "argument_equality" in serialized


def test_redundant_eq_is_fine():
    r = run_proof(proof(steps=[
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "eq", "left": "a", "right": "b"},
    ]))
    assert r["verdict"] == "valid"
    assert r["steps"][1]["declared_equal"] is True


def test_symmetric_congruence_key_order():
    # g(a, c) vs g(b, a): first arguments match but second ones do not (c ≢ a)
    r = run_proof(proof(steps=[
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "claim", "left": ["g", "a", "c"], "right": ["g", "b", "a"]},
    ]))
    assert r["verdict"] == "invalid"


# ------------------------------------------------------------- expired scopes
def test_inner_equality_vanishes_after_pop():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {}},
        steps=[
            {"type": "push"},
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "claim", "left": "a", "right": "b"},
            {"type": "pop"},
            {"type": "claim", "left": "a", "right": "b"},
        ],
    ))
    assert r["accepted"] is False
    assert r["failure_step"] == 4
    assert r["error_code"] == "untenable_claim"
    assert "失效" in r["error"] or "不等价" in r["error"]


def test_inner_congruence_vanishes_after_pop():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {"f": 1}},
        steps=[
            {"type": "push"},
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "pop"},
            {"type": "claim", "left": ["f", "a"], "right": ["f", "b"]},
        ],
    ))
    assert r["verdict"] == "invalid"
    assert r["failure_step"] == 3


def test_outer_congruence_recloses_for_terms_first_seen_inside_scope():
    # a=b lives in the base scope; f(a),f(b) only enter the graph inside an
    # inner scope (via its diseq). After popping the inner scope they must
    # still be congruent on the strength of the surviving outer equality.
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {"f": 1}},
        steps=[
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "push"},
            {"type": "neq", "left": ["f", "a"], "right": ["f", "b"]},
            {"type": "pop"},
            {"type": "claim", "left": ["f", "a"], "right": ["f", "b"]},
        ],
    ))
    assert r["verdict"] == "valid", r["error"]


def test_inner_argument_equality_blocks_reclose_after_pop():
    # mirror case: f(a)=f(b) depended on the inner equality a=b; after the
    # pop the applications must split apart again.
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {"f": 1}},
        steps=[
            {"type": "push"},
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "claim", "left": ["f", "a"], "right": ["f", "b"]},
            {"type": "pop"},
            {"type": "claim", "left": ["f", "a"], "right": ["f", "b"]},
        ],
    ))
    assert r["verdict"] == "invalid"
    assert r["failure_step"] == 4


def test_inner_disequality_vanishes_after_pop():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {}},
        steps=[
            {"type": "push"},
            {"type": "neq", "left": "a", "right": "b"},
            {"type": "pop"},
            {"type": "eq", "left": "a", "right": "b"},
        ],
    ))
    assert r["verdict"] == "valid"


def test_nested_scopes_roll_back_independently():
    r = run_proof(proof(
        sig={"constants": ["a", "b", "c"], "functions": {}},
        steps=[
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "push"},
            {"type": "eq", "left": "b", "right": "c"},
            {"type": "claim", "left": "a", "right": "c"},
            {"type": "pop"},
            {"type": "claim", "left": "a", "right": "c"},
        ],
    ))
    assert r["failure_step"] == 5
    # outer equality a=b must survive the pop
    r2 = run_proof(proof(
        sig={"constants": ["a", "b", "c"], "functions": {}},
        steps=[
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "push"},
            {"type": "eq", "left": "b", "right": "c"},
            {"type": "pop"},
            {"type": "claim", "left": "a", "right": "b"},
        ],
    ))
    assert r2["verdict"] == "valid"


def test_scope_depth_reported():
    r = run_proof(proof(
        sig={"constants": [], "functions": {}},
        steps=[{"type": "push"}, {"type": "push"}, {"type": "pop"}],
    ))
    assert [s["scope_depth"] for s in r["steps"]] == [1, 2, 1]
    assert r["scope_depth"] == 1


# --------------------------------------------------------------- contradictions
def test_contradiction_against_outer_diseq_claimable_then_gone():
    r = run_proof(proof(
        sig={"constants": ["a", "b", "c"], "functions": {}},
        steps=[
            {"type": "neq", "left": "a", "right": "b"},
            {"type": "push"},
            {"type": "eq", "left": "a", "right": "c"},
            {"type": "eq", "left": "c", "right": "b"},
            {"type": "claim"},
            {"type": "pop"},
            {"type": "claim", "left": "a", "right": "b"},
        ],
    ))
    assert r["accepted"] is False  # the last claim is the first untenable one
    assert r["failure_step"] == 6
    assert all(s["ok"] for s in r["steps"][:6])
    # justification of the contradiction cites both sides
    jtree = r["steps"][4]["justification"]
    assert jtree["rule"] == "contradiction"
    assert "disequality_declaration" in str(jtree)


def test_congruence_contradiction_with_disequality():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {"f": 1}},
        steps=[
            {"type": "neq", "left": ["f", "a"], "right": ["f", "b"]},
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "claim"},
        ],
    ))
    assert r["verdict"] == "contradiction"
    assert r["accepted"] is True


def test_trailing_contradiction_state_survives_without_claim():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {}},
        steps=[
            {"type": "neq", "left": "a", "right": "b"},
            {"type": "eq", "left": "a", "right": "b"},
        ],
    ))
    # direct same-level conflict is rejected at the eq step instead
    assert r["verdict"] == "invalid"
    assert r["failure_step"] == 1
    assert r["error_code"] == "same_level_conflict"


# ------------------------------------------------------------- same-level conflict
def test_eq_then_neq_same_level_rejected():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {}},
        steps=[
            {"type": "push"},
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "neq", "left": "a", "right": "b"},
        ],
    ))
    assert r["failure_step"] == 2
    assert r["error_code"] == "same_level_conflict"


def test_neq_then_eq_same_level_rejected():
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {}},
        steps=[
            {"type": "neq", "left": "a", "right": "b"},
            {"type": "eq", "left": "b", "right": "a"},
        ],
    ))
    assert r["failure_step"] == 1
    assert r["error_code"] == "same_level_conflict"


def test_conflict_through_outer_equality_is_not_same_level():
    # outer a=b; inner neq a=b surfaces a contradiction instead of a hard error
    r = run_proof(proof(
        sig={"constants": ["a", "b"], "functions": {}},
        steps=[
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "push"},
            {"type": "neq", "left": "a", "right": "b"},
            {"type": "claim"},
            {"type": "pop"},
        ],
    ))
    assert r["verdict"] == "valid"
    assert r["steps"][2]["declared_unequal"] is True
    assert r["steps"][3]["justification"]["rule"] == "contradiction"


# --------------------------------------------------------------- malformed input
def test_unknown_constant():
    r = run_proof(proof(steps=[{"type": "eq", "left": "x", "right": "a"}]))
    assert r["error_code"] == "unknown_symbol"
    assert "steps[0]" in r["error_position"]


def test_unknown_function():
    r = run_proof(proof(steps=[{"type": "eq", "left": ["h", "a"], "right": "a"}]))
    assert r["error_code"] == "unknown_symbol"


def test_arity_mismatch_too_few():
    r = run_proof(proof(steps=[{"type": "eq", "left": ["f", "a", "b"], "right": "a"}]))
    assert r["error_code"] == "arity_mismatch"


def test_arity_mismatch_zero_arg_function():
    r = run_proof(proof(steps=[{"type": "eq", "left": ["f"], "right": "a"}]))
    assert r["error_code"] == "arity_mismatch"


def test_empty_stack_pop():
    r = run_proof(proof(steps=[{"type": "pop"}]))
    assert r["error_code"] == "empty_stack_pop"
    assert "空栈" in r["error"]


def test_claim_contradiction_when_none():
    r = run_proof(proof(steps=[{"type": "claim"}]))
    assert r["error_code"] == "untenable_claim"


def test_invalid_signature_duplicate_constant():
    r = run_proof(proof(sig={"constants": ["a", "a"], "functions": {}}, steps=[]))
    assert r["error_code"] == "invalid_signature"


def test_invalid_signature_name_clash():
    r = run_proof(proof(sig={"constants": ["f"], "functions": {"f": 1}}, steps=[]))
    assert r["error_code"] == "invalid_signature"


def test_step_limit_enforced():
    steps = [{"type": "push"}] * (MAX_STEPS + 1)
    r = run_proof(proof(steps=steps))
    assert r["error_code"] == "too_many_steps"


def test_first_failing_claim_stops_playback():
    # results must only contain steps up to and including the failing one
    r = run_proof(proof(steps=[
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "claim", "left": "c", "right": "d"},
        {"type": "eq", "left": "a", "right": "c"},
    ]))
    assert r["failure_step"] == 1
    assert len(r["steps"]) == 2
    assert r["steps"][0]["ok"] is True
    assert r["steps"][1]["ok"] is False


# --------------------------------------------------------------- undo-log sanity
def test_rollback_restores_union_metadata_exactly():
    eng = ProofEngine(BASE_SIG)
    eng.execute([{"type": "push"}, {"type": "eq", "left": "a", "right": "b"}])
    assert eng.find(0) == eng.find(1)
    eng.execute([{"type": "pop"}])
    assert eng.find(0) != eng.find(1)
    # a later eq inside a fresh scope still works and rolls back cleanly
    eng.execute([
        {"type": "push"},
        {"type": "eq", "left": "a", "right": "c"},
        {"type": "pop"},
    ])
    assert eng.find(0) != eng.find(2)
