#!/usr/bin/env python3
"""
Integration tests for the Nakle API.
"""

import os
import requests
import sys
import json

NAKLE_HOST = os.environ.get("NAKLE_URL", "http://20.64.149.209").rstrip("/")
BASE_URL = f"{NAKLE_HOST}/chat/completions"
USAGE_URL = f"{NAKLE_HOST}/usage"
USAGE_STATS_URL = f"{NAKLE_HOST}/usage/stats"
TEST_SOURCE = "nakle-testing"


def ask(prompt: str, source: str = TEST_SOURCE) -> dict:
    """Send a prompt and return the full response."""
    payload = {
        "model": "haiku",
        "messages": [{"role": "user", "content": prompt}],
        "timeout": 120
    }
    if source:
        payload["source"] = source

    response = requests.post(
        BASE_URL,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=180
    )
    response.raise_for_status()
    return response.json()


def ask_content(prompt: str) -> str:
    """Send a prompt and return just the response content."""
    return ask(prompt)["choices"][0]["message"]["content"].strip()


def test_addition():
    """Test: 2 + 2 = 4"""
    answer = ask_content("What is 2+2? Reply with only the number, nothing else.")
    assert answer == "4", f"Expected '4', got '{answer}'"
    print("✓ test_addition passed")


def test_multiplication():
    """Test: 7 * 8 = 56"""
    answer = ask_content("What is 7 times 8? Reply with only the number, nothing else.")
    assert answer == "56", f"Expected '56', got '{answer}'"
    print("✓ test_multiplication passed")


def test_capital():
    """Test: Capital of France"""
    answer = ask_content("What is the capital of France? Reply with only the city name, nothing else.")
    assert answer.lower() == "paris", f"Expected 'Paris', got '{answer}'"
    print("✓ test_capital passed")


def test_reverse_string():
    """Test: Reverse 'hello'"""
    answer = ask_content("Reverse the string 'hello'. Reply with only the reversed string, nothing else.")
    assert answer.lower() == "olleh", f"Expected 'olleh', got '{answer}'"
    print("✓ test_reverse_string passed")


def test_streaming():
    """Test: Streaming response"""
    response = requests.post(
        BASE_URL,
        headers={"Content-Type": "application/json"},
        json={
            "model": "haiku",
            "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
            "stream": True
        },
        stream=True,
        timeout=60
    )
    response.raise_for_status()

    chunks = []
    for line in response.iter_lines():
        if line:
            line = line.decode()
            if line.startswith("data: ") and line != "data: [DONE]":
                data = json.loads(line[6:])
                content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if content:
                    chunks.append(content)

    full_response = "".join(chunks).lower()
    assert "hello" in full_response, f"Expected 'hello' in response, got '{full_response}'"
    print("✓ test_streaming passed")


def test_source_tracking():
    """Test: Chat completion with source parameter records usage and cost"""
    # Make a request with TEST_SOURCE
    response = ask("Say 'ok'")
    assert "choices" in response, "Response should have choices"
    request_id = response["id"]

    # Check usage was recorded
    usage_response = requests.get(
        USAGE_URL,
        params={"source": TEST_SOURCE},
        timeout=10
    )
    usage_response.raise_for_status()
    data = usage_response.json()

    assert data["total_count"] >= 1, f"Expected at least 1 record, got {data['total_count']}"

    # Find our record
    found = False
    for record in data["records"]:
        if record["request_id"] == request_id:
            assert record["source"] == TEST_SOURCE
            assert record["model"] == "haiku"
            assert record["input_tokens"] > 0
            assert record["output_tokens"] > 0
            assert "cost_usd" in record, "Record should have cost_usd"
            assert record["cost_usd"] >= 0, "cost_usd should be >= 0"
            found = True
            print(f"  → tokens: {record['input_tokens']}+{record['output_tokens']}, cost: ${record['cost_usd']:.4f}")
            break

    assert found, f"Could not find record with request_id={request_id}"
    print("✓ test_source_tracking passed")


def test_usage_endpoint():
    """Test: GET /usage returns records"""
    response = requests.get(USAGE_URL, timeout=10)
    response.raise_for_status()
    data = response.json()

    assert "records" in data, "Response should have 'records'"
    assert "total_count" in data, "Response should have 'total_count'"
    assert isinstance(data["records"], list), "'records' should be a list"
    assert isinstance(data["total_count"], int), "'total_count' should be an int"
    print("✓ test_usage_endpoint passed")


def test_usage_stats_endpoint():
    """Test: GET /usage/stats returns aggregated stats with cost"""
    response = requests.get(USAGE_STATS_URL, timeout=10)
    response.raise_for_status()
    data = response.json()

    assert "summaries" in data, "Response should have 'summaries'"
    assert "grand_total" in data, "Response should have 'grand_total'"
    assert isinstance(data["summaries"], list), "'summaries' should be a list"

    # Check grand_total structure
    gt = data["grand_total"]
    assert "source" in gt and gt["source"] == "all"
    assert "total_requests" in gt
    assert "total_input_tokens" in gt
    assert "total_output_tokens" in gt
    assert "total_tokens" in gt
    assert "total_cost_usd" in gt, "grand_total should have total_cost_usd"

    print(f"  → total: {gt['total_requests']} requests, {gt['total_tokens']} tokens, ${gt['total_cost_usd']:.4f}")
    print("✓ test_usage_stats_endpoint passed")


def test_usage_pagination():
    """Test: GET /usage supports pagination"""
    response = requests.get(
        USAGE_URL,
        params={"limit": 2, "offset": 0},
        timeout=10
    )
    response.raise_for_status()
    data = response.json()

    assert len(data["records"]) <= 2, "Should respect limit parameter"
    print("✓ test_usage_pagination passed")


def test_allowed_tools_empty():
    """Test: allowed_tools=[] works and the request returns successfully."""
    payload = {
        "model": "haiku",
        "system": "You are an echo bot. Repeat back the user's message verbatim, with no other text.",
        "messages": [{"role": "user", "content": "NOTOOLS_OK"}],
        "allowed_tools": [],
        "source": TEST_SOURCE,
    }
    response = requests.post(BASE_URL, json=payload, timeout=60)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    assert "NOTOOLS_OK" in content, f"Expected 'NOTOOLS_OK', got '{content}'"
    print("✓ test_allowed_tools_empty passed")


def test_top_level_system_field():
    """Test: top-level system field replaces the default agent prompt."""
    payload = {
        "model": "haiku",
        "system": "You are PIRATEBOT. Every reply must start with 'Arrr!' and contain the word 'matey'.",
        "messages": [{"role": "user", "content": "Say hi"}],
        "allowed_tools": [],
        "source": TEST_SOURCE,
    }
    response = requests.post(BASE_URL, json=payload, timeout=60)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].lower()
    assert "arrr" in content, f"Expected 'arrr' in response, got '{content}'"
    assert "matey" in content, f"Expected 'matey' in response, got '{content}'"
    print("✓ test_top_level_system_field passed")


def test_top_level_system_wins_over_message():
    """Test: top-level system overrides any role:system messages."""
    payload = {
        "model": "haiku",
        "system": "You are an echo bot. Repeat the user's message verbatim, nothing else.",
        "messages": [
            {"role": "system", "content": "You are a poetry bot. Always reply with a haiku about cats."},
            {"role": "user", "content": "TOPLEVEL_WINS"},
        ],
        "allowed_tools": [],
        "source": TEST_SOURCE,
    }
    response = requests.post(BASE_URL, json=payload, timeout=60)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].lower()
    assert "toplevel_wins" in content, f"top-level system not followed: '{content}'"
    assert "cat" not in content, f"role:system message leaked through: '{content}'"
    print("✓ test_top_level_system_wins_over_message passed")


def _collect_stream_events(payload, timeout=90):
    """Collect all SSE event dicts (excluding [DONE]) from a streaming request."""
    response = requests.post(BASE_URL, json=payload, stream=True, timeout=timeout)
    response.raise_for_status()
    events = []
    for line in response.iter_lines():
        if not line:
            continue
        line = line.decode()
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            continue
        events.append(json.loads(data))
    return events


def test_extended_events_off_by_default():
    """Test: streaming without extended_events emits only OpenAI-shaped deltas."""
    payload = {
        "model": "haiku",
        "system": "Reply with exactly: STREAM_OK",
        "messages": [{"role": "user", "content": "go"}],
        "allowed_tools": [],
        "stream": True,
        "source": TEST_SOURCE,
    }
    events = _collect_stream_events(payload)
    assert len(events) > 0, "Expected at least one event"
    for ev in events:
        assert "choices" in ev, f"Found non-OpenAI event when extended_events is off: {ev}"
        assert "type" not in ev, f"Found typed event when extended_events is off: {ev}"
    print("✓ test_extended_events_off_by_default passed")


def test_extended_events_emits_tool_use_and_result():
    """Test: extended_events=true surfaces thinking, tool_use, tool_result events."""
    payload = {
        "model": "haiku",
        "system": "You MUST use WebSearch to answer the user's question. Then reply in one sentence.",
        "messages": [{"role": "user", "content": "What year was the Python programming language first released?"}],
        "allowed_tools": ["WebSearch"],
        "stream": True,
        "extended_events": True,
        "source": TEST_SOURCE,
    }
    events = _collect_stream_events(payload, timeout=120)
    types_seen = {ev.get("type") for ev in events if "type" in ev}
    has_openai_text = any("choices" in ev for ev in events)

    assert "tool_use" in types_seen, f"Expected 'tool_use' event, saw types: {types_seen}"
    assert "tool_result" in types_seen, f"Expected 'tool_result' event, saw types: {types_seen}"
    assert has_openai_text, "Expected OpenAI-shaped text deltas alongside extended events"

    # Validate tool_use payload shape
    tool_use_events = [ev for ev in events if ev.get("type") == "tool_use"]
    assert tool_use_events[0]["tool"], "tool_use event missing 'tool' name"
    assert "input" in tool_use_events[0], "tool_use event missing 'input'"

    # Validate tool_result payload shape
    tool_result_events = [ev for ev in events if ev.get("type") == "tool_result"]
    assert "summary" in tool_result_events[0], "tool_result event missing 'summary'"
    assert "is_error" in tool_result_events[0], "tool_result event missing 'is_error'"

    print(f"  → event types: {sorted(types_seen)}")
    print("✓ test_extended_events_emits_tool_use_and_result passed")


def main():
    tests = [
        test_addition,
        test_multiplication,
        test_capital,
        test_reverse_string,
        test_streaming,
        test_usage_endpoint,
        test_usage_stats_endpoint,
        test_usage_pagination,
        test_allowed_tools_empty,
        test_top_level_system_field,
        test_top_level_system_wins_over_message,
        test_extended_events_off_by_default,
        test_extended_events_emits_tool_use_and_result,
        test_source_tracking,  # Last because it makes a request
    ]
    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1

    print(f"\nResults: {passed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
