"""Manual, opt-in smoke test for the real OpenAI Responses provider."""

from __future__ import annotations

import os

from sonic_agent import ModelAccess, OpenAIResponsesProvider, ProviderError


model = os.environ.get("SONIC_OPENAI_MODEL")
if not model:
    raise SystemExit("Set SONIC_OPENAI_MODEL to the model you intend to call.")
if os.environ.get("SONIC_ALLOW_REMOTE") != "1":
    raise SystemExit("Set SONIC_ALLOW_REMOTE=1 to explicitly authorize this remote smoke test.")

provider = OpenAIResponsesProvider(model, max_output_tokens=64)
access = ModelAccess(
    allow_remote=True,
    allowed_origins=("https://api.openai.com",),
    grant_id="manual-openai-smoke",
)

try:
    answer = provider.complete(
        [{"role": "user", "content": "Reply with exactly: sonic provider ready"}],
        access=access,
    )
except ProviderError as error:
    raise SystemExit(f"Provider failed safely [{error.code}]: {error.safe_message}") from None

print(answer.text)
if answer.metadata is not None:
    print({
        "model": answer.metadata.resolved_model,
        "response_id": answer.metadata.response_id,
        "request_id": answer.metadata.request_id,
        "latency_ms": answer.metadata.latency_ms,
        "usage": answer.metadata.usage,
    })
