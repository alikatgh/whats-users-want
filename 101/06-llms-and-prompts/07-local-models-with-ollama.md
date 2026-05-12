# 07 — Local models with Ollama

You don't have an OpenAI budget. You don't want ticket text with
user IDs and money amounts to leave your laptop. You want the
extraction to be reproducible six months from now even if a
hosted API has been deprecated.

You need a model that runs locally. The project picks Ollama
running `gemma3:4b` over HTTP on `localhost:11434`. No paid
APIs. No data egress. Reproducible across machines that pull the
same model tag.

This lesson teaches you the HTTP pattern, why we use the
standard library's `urllib` instead of the `ollama` Python
package, what the JSON payload looks like, and why
[`local_llm_model_comparison.md`](../../outputs/option2_20260502_150055/local_llm_model_comparison.md)
concludes that 4 B parameters is the smallest usable size for
this task.

## Why local matters

Three reasons, in priority order.

**Privacy.** The BIGO/IMO ticket dataset contains user IDs,
ban reasons, claims of being defrauded, and money amounts. Even
if OpenAI's terms allow you to send it, the operational risk —
data leak, compliance question, audit log — argues against
sending it out at all. With Ollama, the bytes stay on the
laptop.

**Cost.** 6,728 tickets at GPT-4-class pricing was prohibitive
for the project. The script supports OpenAI (lesson 06) but
defaults to local. The 250 tickets in the reference run took
about 15 minutes on Apple Silicon CPU and zero dollars.

**Reproducibility.** A model tag like `gemma3:4b` points at a
specific weights file with a specific hash. Pull that tag from
Ollama on a different machine in a year and you get the same
model. Hosted APIs deprecate models on their own schedule.
Reproducing a 2026 extraction in 2027 with a hosted API is a
maintenance problem; with Ollama, it's `ollama pull gemma3:4b`.

## The HTTP pattern

Ollama exposes an HTTP API at `localhost:11434`. The chat
endpoint is `POST /api/chat`. The request body is JSON with
fields for model, messages, options, and a `format: "json"`
flag for JSON mode. The response body is JSON with the model's
reply under `message.content`.

You could install the `ollama` Python package and call it from
there. The project doesn't. It uses
`urllib.request.Request` from the standard library. Two reasons:
zero extra dependencies, and the HTTP pattern is short enough
that wrapping it in a function is fine.

The pattern shows up twice in the codebase. First in
[`ollama_chat_json`](../../scripts/llm_extract_rich_tickets.py)
for ticket extraction:

```python
def ollama_chat_json(model: str, ollama_url: str, timeout: int, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ollama_url.rstrip("/") + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed. Is Ollama running at {ollama_url}? {exc}") from exc
    content = (body.get("message") or {}).get("content") or "{}"
    return parse_json_object(content)
```

Second in
[`call_ollama`](../../scripts/label_user_wants.py) for
cluster-title labeling:

```python
def call_ollama(model: str, ollama_url: str, prompt: str, timeout: int) -> dict:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        ollama_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {ollama_url}. Is it running? ({exc})"
        ) from exc
    content = (body.get("message") or {}).get("content") or "{}"
    return parse_json_object(content)
```

Same pattern. `num_ctx` differs (8192 for ticket extraction
because tickets are long, 4096 for cluster labeling because the
prompt is small) and the system prompt is different, but the
HTTP shape is identical. Small enough to read twice.

## Walk the payload

```python
{
    "model": model,
    "stream": False,
    "format": "json",
    "options": {
        "temperature": 0,
        "num_ctx": 8192,
    },
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
}
```

`model`. The Ollama tag for the model to use. Examples:
`gemma3:4b`, `gemma3:1b`, `llama3.1:8b`, `qwen2.5:7b`. The
runtime loads the weights from the local Ollama cache the first
time you use a tag, then keeps them in memory for subsequent
calls. If the tag isn't pulled, the request fails — you have to
`ollama pull <tag>` first.

`stream: False`. Ollama can stream tokens as they're generated
(`stream: True` returns a series of newline-delimited JSON
chunks). For batch extraction we don't want streaming — we want
one parse-able response per call. `stream: False` collects the
full response and returns it as one JSON body.

`format: "json"`. Ollama's JSON mode flag (lesson 02). Tells the
runtime to constrain decoding so the output is valid JSON.

`options.temperature: 0`. Greedy decoding (lesson 01). Same
input always produces same output.

`options.num_ctx: 8192`. Context window size in tokens. Ollama's
default is 2048 in older builds, 4096 in newer ones. We pass
8192 explicitly because some BIGO tickets, after compaction to
6,500 chars, are 2,000+ tokens. Adding the prompt and schema, a
2048-token window would clip the input silently. 8192 is enough
headroom for our longest tickets plus the schema and the system
prompt.

`messages`. The chat history. Two entries: the system prompt
and the user prompt. The role-tag pattern is the standard
chat-API shape.

## Walk the HTTP request

```python
data = json.dumps(payload).encode("utf-8")
request = urllib.request.Request(
    ollama_url.rstrip("/") + "/api/chat",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
```

`json.dumps(payload).encode("utf-8")`. Convert the Python dict
to a JSON string, then to bytes. `urlopen` writes bytes to the
socket; it doesn't encode for you. Skipping the `.encode("utf-8")`
gives you a TypeError.

`ollama_url.rstrip("/") + "/api/chat"`. Defensive URL building.
If the user passes `http://localhost:11434/`, the trailing slash
gets stripped so we don't end up with `//api/chat`. Either form
of the input works.

`headers={"Content-Type": "application/json"}`. Tells Ollama to
parse the body as JSON. Without it, Ollama's HTTP server may
fall back to form parsing and fail.

`method="POST"`. Explicit verb. `urllib.request.Request`
defaults to GET when `data` is None, POST when data is given.
Being explicit avoids surprises in code review.

```python
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
except urllib.error.URLError as exc:
    raise RuntimeError(f"Ollama request failed. Is Ollama running at {ollama_url}? {exc}") from exc
```

`with urllib.request.urlopen(request, timeout=timeout) as response:`.
Context manager closes the socket even if parsing throws. The
`timeout` argument is in seconds; we pass 180 seconds for ticket
extraction because `gemma3:4b` on CPU can take that long on a
big ticket. 120 seconds for the labeling script because cluster
prompts are smaller.

`response.read().decode("utf-8")`. Read the full body as bytes,
decode to a string, then `json.loads`. For non-streaming
responses this gets you the entire reply in one shot.

`except urllib.error.URLError as exc`. Catches connection
refused, name resolution failure, and timeout. We re-raise as
`RuntimeError` with a friendlier message (mentions the URL,
asks "is Ollama running") and chain the original via `from exc`
so the traceback shows both layers. This is what
debuggability looks like — the error message tells you what to
check, and the chained traceback preserves the original cause.

## The response shape

Ollama returns:

```json
{
  "model": "gemma3:4b",
  "created_at": "2026-05-03T01:46:47.123456789Z",
  "message": {
    "role": "assistant",
    "content": "{\"source_row\": \"615\", \"literal_request\": \"...\"}"
  },
  "done": true,
  ...
}
```

The model's actual output is `body["message"]["content"]`. With
JSON mode on, that string is valid JSON. Without JSON mode, it's
prose that may or may not contain JSON.

```python
content = (body.get("message") or {}).get("content") or "{}"
return parse_json_object(content)
```

`(body.get("message") or {}).get("content")` is defensive
chaining. If `body["message"]` is missing or null, we
substitute `{}` so the second `.get` doesn't crash. If
`content` is also missing or null, we substitute `"{}"` so
`parse_json_object` doesn't crash. Cheap insurance against API
drift.

[`parse_json_object`](../../scripts/llm_extract_rich_tickets.py)
strips markdown fences and slices to the outermost braces in
case the model still leaks prose despite JSON mode (small models
sometimes do). Then it calls `json.loads`. The combination of
JSON mode + defensive parsing + a try/except in
`label_user_wants.py` (which returns `{}` on parse failure)
covers all the cases we've seen.

## Comparing model sizes

Ollama lets you swap models by tag.
[`local_llm_model_comparison.md`](../../outputs/option2_20260502_150055/local_llm_model_comparison.md)
records what happened when we tried three sizes:

```
| model_test | mode | rows | ok_rows | bad_outputs | errors | ok_rate | unique_jobs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemma3:270m direct | direct full schema | 10 | 0 | 10 | 0 | 0.0 | 1 |
| gemma3:1b direct | direct full schema | 10 | 9 | 1 | 0 | 0.9 | 2 |
| gemma3:1b hybrid | rules evidence + local narrative | 25 | 25 | 0 | 0 | 1.0 | 5 |
| gemma3:4b direct | direct full schema + enum alias postprocess | 50 | 50 | 0 | 0 | 1.0 | 8 |
```

Read each row.

`gemma3:270m direct`: 0% valid. The 270M-parameter model
returned empty required fields on every smoke-test row. Not
useful for extraction. The model is too small to hold the
schema and the ticket and a coherent answer simultaneously.
It's roughly the size of small distilled models from a few years
ago and the capability is similar — fine for autocomplete or
embeddings, useless for instructing.

`gemma3:1b direct`: 90% valid (9 of 10). The pipeline works,
but with a critical caveat: the model collapsed jobs heavily
into `recover_access`. Only 2 unique job values across 9 valid
rows. The model wasn't reading the ticket carefully enough to
discriminate between, say, an account-recovery ticket and a
fraud-dispute ticket. Both became `recover_access`.

`gemma3:1b hybrid`: 100% valid (25 of 25). Same model, hybrid
backend. The rules layer's `job_to_be_done` survives because
the model isn't allowed to reclassify. The model only writes
narrative, which it does adequately. 5 unique jobs across 25
rows — diversity comes from the rules layer. **This is what
makes a small model viable.**

`gemma3:4b direct`: 100% valid (50 of 50). Eight unique jobs.
At this size the model is finally strong enough to read the
ticket, follow the schema, pick a job that fits, and write
narrative. It's the smallest size we found that worked in
direct mode.

The conclusion in the markdown: "`gemma3:4b` direct plus
enum-alias postprocessing is the best local path so far: 50/50
valid rows in the 50-ticket test." On the full 250-ticket
run, it produced 248 valid + 2 bad_output, a 0.8% failure rate.

The 4 B threshold is empirical, not theoretical. A different
4 B model from a different family might fail at this task. A
different task might be solvable with a 1 B model. The number
to remember isn't "4 B"; it's "you have to test on your data".
The model-comparison file is the artifact of that testing for
this specific dataset.

## Why hybrid rescues smaller models

The hybrid backend's value proposition is on the table above.
Direct `gemma3:1b` is at 90% with 2 unique jobs. Hybrid
`gemma3:1b` is at 100% with 5 unique jobs. The same model, used
the same way except the rules layer handles classification, goes
from "barely works" to "fully works" because we removed the
hard part.

This means: if you're stuck with a smaller model (say, on a
machine with limited RAM), the hybrid backend is the way to use
it. Don't ask the model to do the part it can't; let the rules
layer carry the structure and let the model carry the
sentences.

The hybrid backend also benefits from `gemma3:4b`. The hybrid
output with the larger model is the project's daily default
because it gets you the rules layer's reliability *and* the
larger model's narrative quality.

## What about model upgrades?

Six months from now, a `gemma4:1b` or `phi5:mini` may exist that
hits the same accuracy at smaller size. The pattern in this
module is built to absorb that change.

To swap models:

1. `ollama pull <new-tag>`.
2. Run a comparison: `python scripts/llm_extract_rich_tickets.py
   ... --backend ollama --model <new-tag> --limit 50 --output-stem
   compare_<tag>`.
3. Read the JSONL, count `_status` values, count unique jobs.
4. If the numbers are at least as good as the current default,
   set `LOCAL_LLM_MODEL=<new-tag>` in the environment and
   re-run.

The pipeline doesn't know the difference. The validator and the
alias map work the same. The HTTP pattern doesn't change. Model
upgrades are local, contained, and reversible.

## Privacy and reproducibility together

A subtle benefit of the local stack: privacy and reproducibility
become the same thing. If the model runs on your laptop, the
weights are on your disk, and the model tag pins them. There's
no question about "did the API change behavior between runs" —
the bytes are the same. There's also no question about "where
did the data go" — nowhere.

This is what makes the project's data flow auditable. The
manager who reads the dashboard's "this user wants their account
back" can trust that:

- The ticket text was read by software running on a known
  machine.
- The model that wrote the interpretation has a known
  fingerprint (the model tag plus the file hash).
- The validator and alias map ran on a known commit (in version
  control).
- Nothing was sent to a third-party service.

For a support-data dashboard, that auditability is worth a lot.
The 0.8% failure rate is the cost.

## Try it

Confirm Ollama is running, list installed models, run a single
extraction by hand, and compare against `gemma3:1b`.

```bash
# Is Ollama up?
curl -s http://localhost:11434/api/tags | python -m json.tool | head -30

# Pull both models if you haven't
ollama pull gemma3:4b
ollama pull gemma3:1b
```

```python
import json
import urllib.request

def ollama_one(model, system_prompt, user_prompt):
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    request = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["message"]["content"]

system = "You extract support-ticket meaning into JSON. Return one JSON object only."
user = (
    "Ticket text: I was banned for no reason. Please help me get my account back.\n\n"
    'Return JSON: {"job_to_be_done": "<one of: recover_access, prove_innocence, other>", '
    '"summary": "<one short sentence>"}'
)

for model in ("gemma3:4b", "gemma3:1b"):
    print(f"\n=== {model} ===")
    print(ollama_one(model, system, user))
```

You should see both models return valid JSON. The 4 B model is
likely to pick `prove_innocence` or `recover_access` based on
"banned for no reason" + "get my account back" — it reads both
clauses. The 1 B model is more likely to collapse to
`recover_access` because "get my account back" is the
strongest single signal and that's all it pays attention to.

Bonus: the HTTP pattern is identical for any chat-style local
model API (LM Studio, llama.cpp's server, vLLM). If you replace
`http://localhost:11434/api/chat` with the equivalent endpoint
for one of those, the rest of the code works unchanged. The
project happens to use Ollama because installation is one shell
command and the HTTP API is stable, but nothing in the pipeline
is Ollama-specific beyond the URL and the payload shape. The
abstraction is the chat-API protocol, not the runtime.
