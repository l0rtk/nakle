#!/usr/bin/env python3
"""
Integration tests for the Nakle API.
"""

import requests
import sys

BASE_URL = "http://20.64.149.209/chat/completions"


def ask(prompt: str) -> str:
    """Send a prompt and return the response content."""
    response = requests.post(
        BASE_URL,
        headers={"Content-Type": "application/json"},
        json={
            "model": "haiku",
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=60
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def test_addition():
    """Test: 2 + 2 = 4"""
    answer = ask("What is 2+2? Reply with only the number, nothing else.")
    assert answer == "4", f"Expected '4', got '{answer}'"
    print("✓ test_addition passed")


def test_multiplication():
    """Test: 7 * 8 = 56"""
    answer = ask("What is 7 times 8? Reply with only the number, nothing else.")
    assert answer == "56", f"Expected '56', got '{answer}'"
    print("✓ test_multiplication passed")


def test_capital():
    """Test: Capital of France"""
    answer = ask("What is the capital of France? Reply with only the city name, nothing else.")
    assert answer.lower() == "paris", f"Expected 'Paris', got '{answer}'"
    print("✓ test_capital passed")


def test_reverse_string():
    """Test: Reverse 'hello'"""
    answer = ask("Reverse the string 'hello'. Reply with only the reversed string, nothing else.")
    assert answer.lower() == "olleh", f"Expected 'olleh', got '{answer}'"
    print("✓ test_reverse_string passed")


def main():
    tests = [test_addition, test_multiplication, test_capital, test_reverse_string]
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
