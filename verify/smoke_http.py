"""HTTP smoke test executed once by the compose verify service.

Exercises the real running web container over HTTP:
  * health check
  * static React page is served
  * a valid proof (equalities + congruence) returns the right verdict with
    expandable justifications
  * same id + same payload replays the frozen result
  * same id + different payload is explicitly rejected (409)
  * an expired-scope equality and an unknown symbol are located precisely
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://web:8000"
failures = []


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print(f"== HTTP smoke against {BASE}")

status, text = request("GET", "/health")
health = json.loads(text)
check("health endpoint 200/ok", status == 200 and health.get("status") == "ok", text)

status, page = request("GET", "/")
check("React page served at /", status == 200 and '<div id="root">' in page, f"status={status}")

valid_payload = {
    "audit_id": "smoke-valid",
    "signature": {"constants": ["a", "b", "c", "d"], "functions": {"f": 1, "g": 2}},
    "steps": [
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "eq", "left": "c", "right": "d"},
        {"type": "claim", "left": ["f", "a"], "right": ["f", "b"]},
        {"type": "claim", "left": ["g", "a", "c"], "right": ["g", "b", "d"]},
    ],
}
status, text = request("POST", "/api/proofs", valid_payload)
r = json.loads(text)
check("valid proof accepted", status == 200 and r["verdict"] == "valid", text[:200])
claim = r["steps"][2]
check(
    "claim carries expandable congruence justification",
    claim["justification"]["rule"] == "equality_path"
    and "congruence" in json.dumps(claim["justification"], ensure_ascii=False),
)
check("congruence pair reported", claim["congruence_pairs"] == [
    {"left": ["f", "a"], "right": ["f", "b"]}
], str(claim["congruence_pairs"]))
check("first response is not a replay", r["replay"] == {"replayed": False, "frozen": True})

status, text = request("POST", "/api/proofs", valid_payload)
r2 = json.loads(text)
check("same id+payload replays frozen result",
      status == 200 and r2["replay"] == {"replayed": True, "frozen": True}
      and r2["verdict"] == "valid", text[:200])

changed = json.loads(json.dumps(valid_payload))
changed["steps"].append({"type": "eq", "left": "a", "right": "c"})
status, text = request("POST", "/api/proofs", changed)
check("changed payload on same id rejected with 409",
      status == 409 and json.loads(text)["error_code"] == "payload_conflict", text[:200])

expired = {
    "audit_id": "smoke-expired",
    "signature": {"constants": ["a", "b"], "functions": {}},
    "steps": [
        {"type": "push"},
        {"type": "eq", "left": "a", "right": "b"},
        {"type": "pop"},
        {"type": "claim", "left": "a", "right": "b"},
    ],
}
status, text = request("POST", "/api/proofs", expired)
r = json.loads(text)
check("expired-scope claim fails at steps[3]",
      r["accepted"] is False and r["failure_step"] == 3
      and r["error_position"] == "steps[3].left/right", text[:200])
check("old evidence after failure is cleared (only 4 steps returned)",
      len(r["steps"]) == 4 and all(s["ok"] for s in r["steps"][:3]))

unknown = {
    "audit_id": "smoke-unknown",
    "signature": {"constants": ["a"], "functions": {"f": 1}},
    "steps": [{"type": "eq", "left": ["f", "ghost"], "right": "a"}],
}
status, text = request("POST", "/api/proofs", unknown)
r = json.loads(text)
check("unknown symbol located and rejected",
      r["accepted"] is False and r["error_position"].startswith("steps[0]"), text[:200])

pop = {
    "audit_id": "smoke-pop",
    "signature": {"constants": [], "functions": {}},
    "steps": [{"type": "pop"}],
}
status, text = request("POST", "/api/proofs", pop)
r = json.loads(text)
check("empty-stack pop rejected", r["accepted"] is False, text[:120])

if failures:
    print(f"\nSMOKE FAILURES: {failures}")
    sys.exit(1)
print("\nHTTP smoke: all checks passed")
