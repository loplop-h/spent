"""Budget alerts -- get warned when spending exceeds a threshold."""

from spent import track
from openai import OpenAI

# Set a $0.05 budget for this session
client = track(OpenAI(), budget=0.05)

# Make calls normally -- you'll see a warning if budget is exceeded
for i in range(10):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Write a haiku about the number {i}."}],
        max_tokens=50,
    )
    print(f"Haiku {i}: {response.choices[0].message.content.strip()}")

# If total cost exceeds $0.05:
# [spent] BUDGET ALERT: $0.0523 spent (budget: $0.05)
