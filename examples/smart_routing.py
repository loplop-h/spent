"""Smart model routing -- automatically use cheaper models for simple tasks."""

from spent import track
from openai import OpenAI

# Enable optimize=True to auto-route calls
client = track(OpenAI(), optimize=True)

# This classification task will be auto-routed to gpt-4o-mini (94% cheaper)
r1 = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Classify as positive/negative: I love this!"}],
    max_tokens=5,
)
print(f"Classification ({r1.model}): {r1.choices[0].message.content}")

# This translation will also be routed to gpt-4o-mini
r2 = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Translate to French: Hello, how are you?"}],
    max_tokens=30,
)
print(f"Translation ({r2.model}): {r2.choices[0].message.content}")

# This coding task stays on gpt-4o (complexity 8/8, needs quality)
r3 = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Write a Python quicksort implementation."}],
    max_tokens=200,
)
print(f"Coding ({r3.model}): generated {len(r3.choices[0].message.content)} chars")

# Summary shows: 2 calls routed to mini, 1 stayed on 4o
