"""API tests: freeze/replay, payload-change rejection, evidence clearing."""
import copy

BASE_PAYLOAD = {
    "audit_id": "audit-001",
    "signature": {"constants": ["a", "b", "c"], "functions": {"f": 1}},
    "steps": [
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "claim", "left": ["f", "a"], "right": ["f", "b"]},
    ],
}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "congruence-audit"}


def test_submit_valid_proof(client):
    r = client.post("/api/proofs", json=BASE_PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["verdict"] == "valid"
    assert body["failure_step"] is None
    assert body["replay"] == {"replayed": False, "frozen": True}
    assert len(body["steps"]) == 2
    # every claim carries an expandable declaration+congruence justification
    j = body["steps"][1]["justification"]
    assert j["rule"] == "equality_path"


def test_same_id_same_payload_replay_is_frozen(client):
    r1 = client.post("/api/proofs", json=BASE_PAYLOAD)
    assert r1.status_code == 200
    first = r1.json()
    r2 = client.post("/api/proofs", json=BASE_PAYLOAD)
    assert r2.status_code == 200
    second = r2.json()
    assert second["replay"]["replayed"] is True
    assert second["replay"]["frozen"] is True
    # frozen result identical apart from the replay flag
    first["replay"] = {"replayed": True, "frozen": True}
    assert first == second


def test_replay_canonical_equivalent_json(client):
    client.post("/api/proofs", json=BASE_PAYLOAD)
    reordered = {
        # JSON object key order shuffled; semantic payload is identical
        "steps": [
            {"right": "b", "left": "a", "type": "eq"},
            {"type": "claim", "right": ["f", "b"], "left": ["f", "a"]},
        ],
        "signature": {"functions": {"f": 1}, "constants": ["a", "b", "c"]},
        "audit_id": "audit-001",
    }
    r = client.post("/api/proofs", json=reordered)
    assert r.status_code == 200
    assert r.json()["replay"]["replayed"] is True


def test_same_id_changed_payload_rejected(client):
    client.post("/api/proofs", json=BASE_PAYLOAD)
    changed = copy.deepcopy(BASE_PAYLOAD)
    changed["steps"].append({"type": "eq", "left": "a", "right": "c"})
    r = client.post("/api/proofs", json=changed)
    assert r.status_code == 409
    body = r.json()
    assert body["error_code"] == "payload_conflict"
    assert body["accepted"] is False
    # the original frozen verdict is untouched
    got = client.get(f"/api/proofs/{BASE_PAYLOAD['audit_id']}").json()
    assert got["verdict"] == "valid"
    assert len(got["steps"]) == 2


def test_changed_signature_is_also_rejected(client):
    client.post("/api/proofs", json=BASE_PAYLOAD)
    changed = copy.deepcopy(BASE_PAYLOAD)
    changed["signature"]["constants"].append("z")
    r = client.post("/api/proofs", json=changed)
    assert r.status_code == 409
    assert r.json()["error_code"] == "payload_conflict"


def test_get_unknown_audit_returns_404(client):
    r = client.get("/api/proofs/nope")
    assert r.status_code == 404


def test_failure_clears_previous_evidence_for_that_submission(client):
    # an invalid submission returns only steps up to and including the
    # failure — stale evidence from later steps must never be present
    payload = copy.deepcopy(BASE_PAYLOAD)
    payload["audit_id"] = "audit-bad"
    payload["steps"] = [
        {"type": "push"},
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "pop"},
        {"type": "claim", "left": "a", "right": "b"},  # expired equality
        {"type": "eq", "left": "a", "right": "c"},     # never executed
    ]
    r = client.post("/api/proofs", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert body["verdict"] == "invalid"
    assert body["failure_step"] == 3
    assert body["error_position"] == "steps[3].left/right"
    assert len(body["steps"]) == 4
    assert body["steps"][-1]["ok"] is False
    assert body["steps"][-1]["error"]


def test_unknown_symbol_localized(client):
    payload = copy.deepcopy(BASE_PAYLOAD)
    payload["audit_id"] = "audit-unknown"
    payload["steps"] = [{"type": "eq", "left": "ghost", "right": "a"}]
    r = client.post("/api/proofs", json=payload)
    body = r.json()
    assert body["accepted"] is False
    assert body["error_position"].startswith("steps[0]")


def test_empty_stack_pop_localized(client):
    payload = copy.deepcopy(BASE_PAYLOAD)
    payload["audit_id"] = "audit-pop"
    payload["steps"] = [{"type": "pop"}]
    body = client.post("/api/proofs", json=payload).json()
    assert body["error_code"] == "empty_stack_pop"


def test_contradiction_verdict(client):
    payload = {
        "audit_id": "audit-contra",
        "signature": {"constants": ["a", "b"], "functions": {}},
        "steps": [
            {"type": "neq", "left": "a", "right": "b"},
            {"type": "push"},
            {"type": "eq", "left": "a", "right": "b"},
            {"type": "claim"},
            {"type": "pop"},
        ],
    }
    body = client.post("/api/proofs", json=payload).json()
    assert body["accepted"] is True
    assert body["verdict"] == "valid"  # contradiction was scoped and popped


def test_validation_error_for_bad_shape(client):
    r = client.post("/api/proofs", json={"audit_id": "", "signature": {}, "steps": []})
    assert r.status_code == 422


def test_two_audits_are_independent(client):
    p1 = copy.deepcopy(BASE_PAYLOAD)
    p2 = copy.deepcopy(BASE_PAYLOAD)
    p2["audit_id"] = "audit-002"
    p2["steps"] = [{"type": "claim", "left": "a", "right": "b"}]
    assert client.post("/api/proofs", json=p1).json()["verdict"] == "valid"
    body2 = client.post("/api/proofs", json=p2).json()
    assert body2["verdict"] == "invalid"
    assert body2["failure_step"] == 0
