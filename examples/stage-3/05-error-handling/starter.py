"""練習 5：Tool 錯誤處理 — Path A（Ollama 默認、本機免費）。

故意讓 fetch_weather 第一次回結構化 error、第二次才成功。觀察 ReAct loop 怎麼
把 error observation 交回 LLM、讓模型自己決定 retry / 改 query / 放棄。
重點：error 是結構化 dict（`{"error", "retry_hint"}`）、不是 Python exception。

跑法：
    pip install -r requirements.txt
    ollama pull qwen2.5:3b
    ollama serve
    python starter.py

驗證：
    python test.py   （用 mock、不打 API）

想看 Anthropic Claude 版本：
    python starter_anthropic.py   （需 ANTHROPIC_API_KEY、$0.003/run）

⚠️ 注意：小 model 對 retry_hint 的 follow-up 較弱、可能直接放棄或無視 hint。
這恰好是教學點——同樣 structured error pattern、不同 model 的「閱讀力」差。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from openai import OpenAI

MODEL = os.environ.get("MODEL", "qwen2.5:3b")
_failure_plan: list[bool] = [True, False]


def set_weather_failures(plan: list[bool]) -> None:
    global _failure_plan
    _failure_plan = list(plan)


def fetch_weather(city: str) -> dict:
    """假的 weather API、用 _failure_plan 決定這次該失敗還是成功。"""
    # 參數安全校驗：防範路徑遍歷與注入攻擊
    if not city or any(char in city for char in ["..", "/", "\\"]):
        return {"error": "Security validation failed: Invalid characters or empty city name."}
    should_fail = _failure_plan.pop(0) if _failure_plan else False
    if should_fail:
        return {"error": "network timeout", "retry_hint": "try again in 1s"}
    return {"city": city, "forecast": "rain", "temperature_c": 24}


TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "fetch_weather",
            "description": "Fetch current weather. If an error is returned, inspect retry_hint before retrying.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
        },
    }
]


def react_loop(question: str, max_iter: int = 5, client: Any = None) -> dict:
    """OpenAI-compat ReAct loop。tool error 是結構化 JSON、放進 tool_result 給 LLM 看。"""
    client = client or OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    messages = [{"role": "user", "content": question}]
    trace: list[dict] = []
    consecutive_failures = 0  # 斷路器計數器

    for step in range(max_iter):
        resp = client.chat.completions.create(
            model=MODEL,
            tools=TOOLS_SPEC,
            messages=messages,
        )
        msg = resp.choices[0].message
        text = msg.content or ""
        tool_calls = msg.tool_calls or []

        assistant_entry: dict = {"role": "assistant", "content": text}
        if tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_entry)

        if resp.choices[0].finish_reason == "stop" or not tool_calls:
            trace.append({"step": step, "thought": text, "tool": None, "obs": None})
            return {"final": text, "trace": trace, "steps": step + 1}

        for tc in tool_calls:
            # 1. 處理 JSON 解析防禦
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as je:
                obs = {
                    "error": "Invalid JSON arguments format",
                    "details": str(je),
                    "raw_arguments": tc.function.arguments,
                }
                args = {}
            else:
                # 2. 處理 Tool 執行時的異常例外
                try:
                    if tc.function.name == "fetch_weather":
                        city = args.get("city")
                        if not city:
                            obs = {"error": "Missing required argument 'city'"}
                        else:
                            obs = fetch_weather(city)
                    else:
                        obs = {"error": f"Unknown tool: {tc.function.name}"}
                except Exception as e:
                    obs = {
                        "error": "Tool execution failed due to an unexpected exception",
                        "exception_type": type(e).__name__,
                        "message": str(e),
                    }
            
            # 3. 斷路器（Circuit Breaker）邏輯
            if isinstance(obs, dict) and "error" in obs:
                consecutive_failures += 1
            else:
                consecutive_failures = 0

            # OpenAI-compat 的 tool message content 接受字串、把 dict 序列化
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(obs, ensure_ascii=False),
            })
            trace.append({"step": step, "thought": text, "tool": tc.function.name, "tool_input": args, "obs": obs})

            # 如果連續失敗達到 3 次，觸發熔斷，直接中斷執行
            if consecutive_failures >= 3:
                circuit_breaker_msg = "熔斷機制觸發：工具呼叫連續失敗達 3 次。已中斷執行以避免虛耗 Token。"
                trace.append({"step": step + 1, "thought": circuit_breaker_msg, "tool": None, "obs": None})
                return {"final": circuit_breaker_msg, "trace": trace, "steps": step + 2, "circuit_breaker_triggered": True}

    return {"final": None, "trace": trace, "steps": max_iter, "truncated": True}


if __name__ == "__main__":
    set_weather_failures([True, False])  # 第一次失敗、第二次成功
    print(f"❓ 問題：Will it rain in Taipei today?（using Ollama {MODEL}）")
    print("-" * 60)

    result = react_loop("Will it rain in Taipei today?")
    for entry in result["trace"]:
        if entry["tool"]:
            print(f"[step {entry['step']}] tool: {entry['tool']}({entry.get('tool_input')}) → {entry['obs']}")
    print("-" * 60)
    print(f"✅ 最終答案：{result['final']}")

    # 寬鬆驗證：loop 至少要看到結構化 error 在 trace 裡（小 model 不一定 retry）
    saw_error = any(isinstance(e["obs"], dict) and "error" in e["obs"] for e in result["trace"])
    assert saw_error, "預期至少一輪 tool 回傳結構化 error"
    print("✅ 練習 5 通過 — 你已用本機 qwen2.5:3b 看見 tool error 在 ReAct loop 裡是 data 不是 exception、$0/run")
