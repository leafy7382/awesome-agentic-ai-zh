<div align="right">
  <a href="./README.md">繁體中文</a> | <strong>简体中文</strong> | <a href="./README.en.md">English</a>
</div>

# 练习 5：Tool 错误处理

对应 [Stage 3 — Tool Use & Agent 入门](../../../stages/03-tool-use-and-hello-agent.zh-Hans.md) 练习 5。

## 为什么这题重要

真实 agent 很少只走成功路径：API 会 timeout、第三方服务暂时不可用、user 传坏参数。这题故意让 `fetch_weather(city)` 第一次回**结构化 error**（`{"error": "network timeout", "retry_hint": "try again in 1s"}`）、第二次才成功；观察 ReAct loop 怎么把 error observation 交回 LLM、让模型自己决定 retry / 改 query / 放弃。

核心观念：**tool error 是数据、不是 exception**。回传结构化 dict、不要 raise。

## 怎么跑 — 两条路径

### Path A（默认、本机免费）

```bash
pip install -r requirements.txt
ollama pull qwen2.5:3b
ollama serve
python starter.py
```

预算：**$0**。3 轮 loop ≈ 10-60 秒。

### Path B（Anthropic、想看 cloud 高质量）

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python starter_anthropic.py
```

预算：每次 ≈ **$0.003**（claude-haiku-4-5、3 轮 messages 累积）。

预期看到（Path A、本机，理想 retry 走法）：

```
❓ 问题：Will it rain in Taipei today?（using Ollama qwen2.5:3b）
------------------------------------------------------------
[step 0] tool: fetch_weather({'city': 'Taipei'}) → {'error': 'network timeout', 'retry_hint': 'try again in 1s'}
[step 1] tool: fetch_weather({'city': 'Taipei'}) → {'city': 'Taipei', 'forecast': 'rain', 'temperature_c': 24}
------------------------------------------------------------
✅ 最终答案：It will rain in Taipei today (24°C).
✅ 练习 5 通过 — tool error 是 data 不是 exception、$0/run
```

## 不花钱验证程序逻辑（mock-based）

```bash
python test.py            # 验 Path A (Ollama) starter.py 逻辑
python test_anthropic.py  # 验 Path B (Anthropic) starter_anthropic.py 逻辑
```

两条 test 都用 `unittest.mock`、不打真 API、$0/run。

## 设计提醒

错误也应该是结构化数据，让 LLM 有 context 做决策：

| Bad | Good |
|---|---|
| `raise Exception("failed")` | `return {"error": "network timeout", "retry_hint": "try again in 1s"}` |
| `return "failed"` | `return {"error": "...", "category": "transient", "retry_hint": "..."}` |
| 直接崩溃 / 未捕获异常 | 在主程序 loop 中使用 `try-except Exception` 捕获意外错误并包装成 `{"error": ...}` 返回给 LLM |
| 未校验 LLM 参数格式 | 在主程序中捕获 `json.JSONDecodeError`，避免 JSON 损坏导致主程序崩溃 |
| 无限 retry | `max_iter` safety + 业务层 retry quota |

只回传 `"failed"` 让模型不知道下一步；加入 `retry_hint`、错误类型与可恢复建议，模型才有足够 context 做决策。同时，在生产环境中，**绝对不能让工具的执行异常（Exceptions）直接传播到主进程**，否则会导致 Agent 主进程崩溃。应使用 `try-except` 捕获所有异常并转化为结构化 JSON 错误返回。此外，应做好 **JSON 解析防御**，避免模型输出格式损坏导致 JSON 解析失败。retry 次数也要有限制，否则 agent 会在坏掉的工具前面无限打转。

## 两个 path 观察重点

**附加观察**：小 model（qwen2.5:3b）对 `retry_hint` 的 follow-up 可能不如 Claude 精细——可能会直接放弃、或无视 hint 重复同一个错。**这恰好是教学点**：production 写好 retry pattern 后，不同 model 对结构化 error 的“阅读力”差距，是选 model 的考量之一（Stage 7 production tier 会再回来讨论）。

| 观察项 | Anthropic Claude haiku | Ollama qwen2.5:3b |
|---|---|---|
| 看到 retry_hint 就 retry | 高机率 | 中机率（可能直接放弃） |
| 连续失败后 graceful end | 稳定 | 可能再 retry 第 3 次 |
| 错误类型分流（transient vs permanent） | 较细致 | 较粗略 |

## 想看更聪明的答案？

预设用 `claude-haiku-4-5`（最便宜）。改成 sonnet：

```bash
MODEL=claude-sonnet-4-6 python starter_anthropic.py
```

或 Ollama path 换更大 model：

```bash
MODEL=qwen2.5:7b python starter.py
```

## 延伸

- **加 retry quota**：在 loop 加 `error_count`、超过 N 次就放弃
- **加 circuit breaker**：连续失败、暂时 stop call（避免 wave-after-wave 打死下游）
- **错误类型分类**：transient（429 / connection）vs permanent（401 / 400）、不同处理
- **Production 级**：看 [`../../stage-1/05-error-handling/`](../../stage-1/05-error-handling/) 的 API-level retry wrapper（exponential backoff + jitter）
