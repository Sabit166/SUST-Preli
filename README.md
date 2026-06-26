# SUST Preli Backend — QueueStorm Investigator

A small FastAPI service that takes a customer support ticket, classifies it
into a `case_type`, finds the relevant transaction in the caller's history,
routes it to the right department with a severity level, and replies with a
JSON envelope that an agent or downstream system can consume.

> The service in this repo is the **judging harness's** `analyze-ticket`
> contract — not a full product. The whole pipeline is keyword/regex based;
> no LLMs, no external DB. The dedup window is in-process only.

---

## What's in the box

- `main.py` — FastAPI app, all classification + routing logic
- `agent.py` — agent entrypoint (Groq by default; xAI Grok via `LLM_PROVIDER=xai`)
- `system_prompt.py` — system prompt for the agent
- `translator.py` — Bangla/Banglish → English prompt used by the agent
- `run_agent_tests.py` — runs the agent against `agent_test_cases.json`
- `test_samples.py` — 10 sample cases (used as the judging fixture)
- `requirements.txt` — Python dependencies
- `run.ps1`, `run.bat`, `run.sh` — convenience launchers (see below)

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET`  | `/health` | readiness probe (always-on) |
| `GET`  | `/analyze-ticket/agent/health` | readiness probe for the LLM route (`ready: true` only when a key is configured) |
| `POST` | `/analyze-ticket` | **offline / judging** — pure keyword + hardcoded templates |
| `POST` | `/analyze-ticket/agent` | **live demo** — runs `agent.handle_ticket()` (Groq or xAI); falls back to the keyword route if the LLM fails or times out |

---

## 1. Prerequisites

- Python 3.10 or newer
- `pip install -r requirements.txt` (FastAPI, uvicorn, pydantic, requests, …)

Verify the install:

```powershell
python -m fastapi --version
python -m uvicorn --version
```

---

## 2. Run the server

> ⚠️ Always launch from the `SUST-Preli/` folder (the one containing
> `main.py`). Launching from the parent folder gives
> `Error: Could not import module "main"`.

### Option A — convenience launcher (recommended)

| Platform | Command |
| --- | --- |
| PowerShell | `.\run.ps1` |
| cmd.exe     | `run.bat` |
| bash / WSL  | `bash run.sh` |

Each script does `Set-Location` to the script's own folder before starting
uvicorn, so you can run them from any cwd.

Default bind: `127.0.0.1:8000`. To change:

```powershell
.\run.ps1 -BindHost 0.0.0.0 -Port 8765
```

```cmd
run.bat 0.0.0.0 8765
```

```bash
bash run.sh 0.0.0.0 8765
```

> 💡 `0.0.0.0` makes the server listen on every interface (good inside a
> VM or container). From your own browser, always use `127.0.0.1` or
> `localhost` — `0.0.0.0` is a *listen* address, not a *navigate* address,
> and Chrome will reject it with `ERR_ADDRESS_INVALID`.

### Option B — direct uvicorn

```powershell
cd D:\SUST_HACKATHON_Preli\SUST-Preli
uvicorn main:app --host 127.0.0.1 --port 8000
```

You should see:

```
INFO:     Started server process [...]
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 3. Confirm it's up

In a second terminal (the server must stay running in the first):

```powershell
curl http://127.0.0.1:8000/health
```

Expected output:

```json
{"status":"ok"}
```

> ℹ️ PowerShell's `curl` is an alias for `Invoke-WebRequest` and behaves
> differently from the unix tool. If you get weird output, run
> `curl.exe` explicitly, or just open `http://127.0.0.1:8000/health`
> in your browser.

---

## 4. Test it via Swagger UI (the easy way)

1. With the server running, open: **http://127.0.0.1:8000/docs**
2. You'll see two endpoints listed:
   - `GET /health` — readiness probe
   - `POST /analyze-ticket` — the actual ticket classifier
3. Click **`POST /analyze-ticket`** to expand it.
4. Click **Try it out** in the top-right of that section.
5. The **Request body** editor appears. **Click `Clear`** to wipe the
   pre-filled example (Swagger sometimes pre-fills a stub that doesn't
   match the request shape).
6. Paste this minimal valid body:

   ```json
   {
     "ticket_id": "TKT-DEMO-01",
     "complaint": "I sent 5000 taka to the wrong number by mistake at 2pm today"
   }
   ```

7. Click **Execute**.
8. Scroll **above** the request body editor to the green-bordered
   **Server response** panel:
   - `Code: 200` means success — the `Response body` contains the classified ticket.
   - `Code: 400` means your body was rejected — the `Response body`'s
     `detail` field tells you why (e.g. `"empty request body"`,
     `"invalid JSON: …"`, `"request body must be a JSON object"`,
     `"invalid request schema"`, `"ticket_id and complaint are required"`).

### Full sample body (with optional fields)

If you want to exercise the transaction-matching logic, include
`transaction_history`:

```json
{
  "ticket_id": "TKT-DEMO-01",
  "complaint": "I sent 5000 taka to the wrong number by mistake at 2pm today",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "transaction_history": [
    {
      "transaction_id": "TXN-DEMO-1",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ]
}
```

### Expected response (200)

```json
{
  "ticket_id": "TKT-DEMO-01",
  "relevant_transaction_id": "TXN-DEMO-1",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer complaint TKT-DEMO-01 relates to transaction TXN-DEMO-1 (case type: wrong_transfer, verdict: consistent). Matched transaction (transfer of 5000 BDT) aligns with the complaint. Routed to dispute_resolution.",
  "recommended_next_action": "Verify the disputed transaction with the customer and initiate the dispute workflow per policy.",
  "customer_reply": "We've noted your concern and will follow up shortly through official channels. Please do not share your PIN or OTP with anyone.",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["wrong_transfer", "consistent", "transaction_match"]
}
```

### Try these too

| What it tests | Body (only the bits that change) |
| --- | --- |
| **Phishing** (always `critical` + `fraud_risk`) | `"complaint": "Someone called and asked for my OTP, I think it's a scam"` |
| **Duplicate payment** | two `transaction_history` entries with same `amount`/`counterparty`/`type` within 60 s |
| **Refund request** | `"complaint": "Please refund my order, I changed my mind"` |
| **Merchant settlement** | `"complaint": "I am a merchant, my settlement of 12000 taka did not arrive"` |
| **Dedup** | Re-Execute the **same** `ticket_id` — `human_review_required` flips to `true` and `reason_codes` gains `"duplicate_ticket_id_recent"` |

---

## 5. Test it from the terminal (no browser)

If you prefer curl / Python over Swagger:

### curl (cmd.exe or bash)

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"ticket_id":"TKT-CLI-01","complaint":"I sent 5000 taka to the wrong number by mistake"}' \
  http://127.0.0.1:8000/analyze-ticket
```

### Python (3 lines)

```python
import urllib.request, json
body = json.dumps({
    "ticket_id": "TKT-CLI-01",
    "complaint": "I sent 5000 taka to the wrong number by mistake",
}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/analyze-ticket",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(json.dumps(json.loads(urllib.request.urlopen(req).read()), indent=2))
```

---

## 6. Run the included tests

```powershell
cd D:\SUST_HACKATHON_Preli\SUST-Preli
python test_samples.py
```

This runs the 10 sample fixtures end-to-end. All 10 should pass.

There are also two helper scripts (not part of the judging suite, just for
sanity checking during development):

```powershell
python _smoke.py             # in-process health + openapi + a couple of payloads
python _validation_matrix.py # 18 bad-input cases, prints each error message
```

---

## 7. Quick troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Error: Could not import module "main"` | uvicorn launched from `D:\SUST_HACKATHON_Preli` (parent) instead of `D:\SUST_HACKATHON_Preli\SUST-Preli` | Use `run.ps1`/`run.bat`/`run.sh`, or `cd` into the project folder first |
| Browser shows `ERR_ADDRESS_INVALID` for `0.0.0.0:8000` | `0.0.0.0` is a listen-only address | Use `http://127.0.0.1:8000/docs` instead |
| `GET /` returns 404 in server logs | Harmless — there's no root route. The service only exposes `/health`, `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect`, and `/analyze-ticket` | Just navigate to `/docs` in the browser |
| Swagger Execute returns 400 `invalid request schema` | The pre-filled body stub doesn't match `AnalyzeRequest` (it shows the *response* shape) | Click `Clear`, then paste the minimal body from §4 |
| `python: command not found` on Windows | `py` launcher not on PATH | Use `python` (from the Microsoft Store install) or `py -3` |
| Server "isn't responding" but uvicorn logs show no errors | Another process is bound to port 8000 | Stop the other uvicorn, or run on a different port (e.g. `.\run.ps1 -Port 8765`) |

---

## 8. API contract summary

### `GET /health`

```json
{ "status": "ok" }
```

### `POST /analyze-ticket`

**Required fields:** `ticket_id` (non-empty string), `complaint` (non-empty string).

**Optional fields:** `language` (`en|bn|mixed`), `channel`
(`in_app_chat|call_center|email|merchant_portal|field_agent`),
`user_type` (`customer|merchant|agent|unknown`), `campaign_context`
(string), `transaction_history` (array of transaction objects), `metadata`
(object).

**Response:** the `AnalyzeResponse` schema shown in §4.

**Error codes:**

- `400` — bad request (empty body, bad JSON, wrong shape, missing required
  field, blank `ticket_id`/`complaint`, bad enum value, …)
- `200` — success

There is no auth, no rate limiting, and no persistence; the dedup signal is
in-process and clears when the server restarts.