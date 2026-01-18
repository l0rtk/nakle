#!/usr/bin/env python3
"""Simple streaming test - watch tokens appear in real-time."""

import requests
import json
import sys

URL = "http://20.64.149.209/chat/completions"

response = requests.post(
    URL,
    json={
        "model": "haiku",
        "messages": [{"role": "user", "content": "Count from 1 to 30 slowly, one number per line."}],
        "stream": True
    },
    stream=True
)

print("Streaming response:\n")
for line in response.iter_lines():
    if line:
        line = line.decode()
        if line.startswith("data: ") and line != "data: [DONE]":
            data = json.loads(line[6:])
            content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if content:
                sys.stdout.write(content)
                sys.stdout.flush()
        elif line == "data: [DONE]":
            print("\n\n[DONE]")
