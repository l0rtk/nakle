#!/usr/bin/env python3
"""
Test script to send prompts to local and Azure VM deployments.
"""

import requests
import json

# Configuration
LOCAL_URL = "http://localhost:8000/chat/completions"
AZURE_URL = "http://20.64.149.209/chat/completions"

def send_prompt(url: str, prompt: str, model: str = "haiku"):
    """Send a prompt and wait for response."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }

    print(f"\n📤 Sending to {url}")
    print(f"Prompt: {prompt}")

    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=300
        )
        response.raise_for_status()
        data = response.json()

        print(f"✅ Response received:")
        print(f"{data['choices'][0]['message']['content']}")
        print(f"Tokens: {data.get('usage', {})}")

    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    prompt = input("Enter your prompt: ")

    print("\n" + "="*60)
    print("AZURE SERVER")
    print("="*60)
    send_prompt(AZURE_URL, prompt)

    print("\n✅ Done!")

if __name__ == "__main__":
    main()
