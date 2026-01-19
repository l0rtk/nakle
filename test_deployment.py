#!/usr/bin/env python3
"""
Integration tests for the Nakle API.
"""

import requests
import sys
import json

BASE_URL = "http://20.64.149.209/chat/completions"
USAGE_URL = "http://20.64.149.209/usage"
USAGE_STATS_URL = "http://20.64.149.209/usage/stats"


def ask(prompt: str, source: str = None) -> dict:
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
    """Test: Chat completion with source parameter records usage"""
    import uuid
    test_source = f"test-{uuid.uuid4().hex[:8]}"

    # Make a request with custom source
    response = ask("Say 'ok'", source=test_source)
    assert "choices" in response, "Response should have choices"
    request_id = response["id"]

    # Check usage was recorded
    usage_response = requests.get(
        USAGE_URL,
        params={"source": test_source},
        timeout=10
    )
    usage_response.raise_for_status()
    data = usage_response.json()

    assert data["total_count"] >= 1, f"Expected at least 1 record, got {data['total_count']}"

    # Find our record
    found = False
    for record in data["records"]:
        if record["request_id"] == request_id:
            assert record["source"] == test_source
            assert record["model"] == "haiku"
            assert record["input_tokens"] > 0
            assert record["output_tokens"] > 0
            found = True
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
    """Test: GET /usage/stats returns aggregated stats"""
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
