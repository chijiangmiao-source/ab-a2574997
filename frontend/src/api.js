const BASE = ''

async function parseResponse(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  return { ok: res.ok, status: res.status, body }
}

export async function fetchHealth() {
  return parseResponse(await fetch(`${BASE}/health`))
}

export async function submitProof(payload) {
  const res = await fetch(`${BASE}/api/proofs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseResponse(res)
}
