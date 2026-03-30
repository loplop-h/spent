"""Track costs across multiple providers simultaneously."""

from spent import track
from openai import OpenAI

# You can also track Anthropic:
# from anthropic import Anthropic
# anthropic_client = track(Anthropic())

openai_client = track(OpenAI())

# All calls from all providers end up in the same dashboard
r = openai_client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=10,
)
print(r.choices[0].message.content)

# View combined costs:
# $ spent report --today
# $ spent ticker         (real-time)
# $ spent web            (web dashboard)
