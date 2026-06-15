<div align="right">
  <a href="./README.md">繁體中文</a> | <a href="./README.zh-Hans.md">简体中文</a> | <strong>English</strong>
</div>

# Exercise 5: Tool Error Handling

Corresponds to [Stage 3 — Tool Use & Agent Intro](../../../stages/03-tool-use-and-hello-agent.en.md) Exercise 5.

## Why this matters

Real agents rarely walk the happy path only: APIs time out, third parties go down, users send bad inputs. This exercise deliberately makes `fetch_weather(city)` return a **structured error** on the first call (`{"error": "network timeout", "retry_hint": "try again in 1s"}`) and succeed on the second; you observe how the ReAct loop hands the error observation back to the LLM and lets the model decide whether to retry, change the query, or give up.

Core idea: **tool errors are data, not exceptions**. Return structured dicts, don't raise.

## How to run — two paths

### Path A (default, free, local)

```bash
pip install -r requirements.txt
ollama pull qwen2.5:3b
ollama serve
python starter.py
```

Budget: **$0**. A 3-round loop takes ~10-60s.

### Path B (Anthropic, cloud-quality comparison)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python starter_anthropic.py
```

Budget: ~**$0.003** per run (claude-haiku-4-5, 3 rounds of accumulating messages).

Expected output (Path A, local, ideal retry-then-succeed path):

```
❓ Question: Will it rain in Taipei today? (using Ollama qwen2.5:3b)
------------------------------------------------------------
[step 0] tool: fetch_weather({'city': 'Taipei'}) → {'error': 'network timeout', 'retry_hint': 'try again in 1s'}
[step 1] tool: fetch_weather({'city': 'Taipei'}) → {'city': 'Taipei', 'forecast': 'rain', 'temperature_c': 24}
------------------------------------------------------------
✅ Final answer: It will rain in Taipei today (24°C).
✅ Exercise 5 passed — tool errors are data, not exceptions, $0/run
```

## Validate the logic without API credits (mock-based)

```bash
python test.py            # validates Path A (Ollama) starter.py logic
python test_anthropic.py  # validates Path B (Anthropic) starter_anthropic.py logic
```

Both test suites use `unittest.mock`, no real API call, $0/run.

## Design reminders

Errors should be structured data, so the LLM has context to make decisions:

| Bad | Good |
|---|---|
| `raise Exception("failed")` | `return {"error": "network timeout", "retry_hint": "try again in 1s"}` |
| `return "failed"` | `return {"error": "...", "category": "transient", "retry_hint": "..."}` |
| Silent crash / Unhandled exceptions | Use `try-except Exception` in the agent loop to catch unexpected tool failures and wrap them as `{"error": ...}` to feed back to LLM |
| Unvalidated LLM argument format | Catch `json.JSONDecodeError` during tool call execution and perform defensive parameter validation (preventing `..` path traversal) |
| Unbounded retry (Burns Token budget) | Implement a **Circuit Breaker** mechanism to automatically abort the loop when tool calls fail 3 consecutive times |

Returning just `"failed"` leaves the model with nothing to act on. Adding `retry_hint`, error category, and recovery suggestions gives the model enough context to choose. In a production environment, **never let tool exceptions propagate unhandled to the main agent loop**, as it will crash the agent. Wrap tool calls in `try-except` blocks to transform raw exceptions into structured JSON error formats.

Additionally, the project has implemented the following safety guards:
- **Defensive Parameter Validation**: Sanitize parameters before tool execution to reject illegal characters such as `..`, `/`, and `\\` that could lead to path traversal or injection attacks.
- **Circuit Breaker Protection**: Maintain a counter in the ReAct loop; once tools **fail 3 times consecutively**, the system automatically aborts to prevent the LLM from entering a loop of futile attempts and wasting Token budget.

## What to watch on each path

**Side observation**: small models (qwen2.5:3b) follow `retry_hint` less reliably than Claude — they might give up immediately or ignore the hint and repeat the same call. **That's exactly the teaching point**: in production, the same retry pattern produces different behaviors depending on how well a model reads structured errors — a real consideration when picking a model (we'll revisit in Stage 7).

| Observation | Anthropic Claude haiku | Ollama qwen2.5:3b |
|---|---|---|
| Retries on `retry_hint` | High | Medium (may give up) |
| Graceful end after repeated failure | Stable | May retry a third time |
| Distinguishing transient vs permanent | Finer | Coarser |

## Want smarter answers?

Default is `claude-haiku-4-5` (cheapest). Try Sonnet:

```bash
MODEL=claude-sonnet-4-6 python starter_anthropic.py
```

Or on the Ollama path, swap to a larger model:

```bash
MODEL=qwen2.5:7b python starter.py
```

## Extensions

- **Add a retry quota** — track `error_count` and give up after N
- **Add a circuit breaker** — after consecutive failures, stop calling for a while (avoids wave-after-wave on a broken downstream)
- **Classify errors** — transient (429 / connection) vs permanent (401 / 400) get different handling
- **Production tier** — see [`../../stage-1/05-error-handling/`](../../stage-1/05-error-handling/) for an API-level retry wrapper with exponential backoff + jitter
