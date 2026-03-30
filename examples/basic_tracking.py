"""Basic cost tracking -- zero code changes approach."""

# Option 1: CLI (recommended, zero code changes)
# $ spent run python your_script.py

# Option 2: One line of code
from spent import track
from openai import OpenAI

client = track(OpenAI())

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is Python?"}],
    max_tokens=100,
)

print(response.choices[0].message.content)
# Cost summary prints automatically on exit
