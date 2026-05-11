"""OpenAI provider — stub.

This file demonstrates how the `LLMProvider` abstraction extends to a second
vendor. The structure mirrors `AnthropicProvider`:

  1. Soft-import the SDK so a missing dep is a clear error, not import death.
  2. Construct the client in __init__.
  3. Convert (system, user) → structured-output call.
  4. Parse and validate the response into `ThreatPostResponse`.

To finish the implementation:
  * `pip install openai`
  * use `client.responses.parse(..., text_format=ThreatPostResponse)` from the
    OpenAI Python SDK (their structured-outputs path)
  * map any retry / error semantics to raise — the generator will fall back

Leaving it stubbed in v1 keeps dependency surface small while proving the
provider abstraction is real and the second vendor is a single file away.
"""
from __future__ import annotations

from ..models import ThreatPostResponse


class OpenAIProvider:
    name: str

    def __init__(
        self,
        *,
        api_key: str | None = None,  # noqa: ARG002 - documents the slot
        model: str = "gpt-4o-mini",
        max_output_tokens: int = 1200,  # noqa: ARG002
    ) -> None:
        self._model = model
        self.name = f"openai:{model}-stub"

    def generate_post(self, system: str, user: str) -> ThreatPostResponse:  # noqa: ARG002
        # Wiring goes here:
        #
        #   from openai import OpenAI
        #   client = OpenAI(api_key=self._api_key)
        #   response = client.responses.parse(
        #       model=self._model,
        #       input=[
        #           {"role": "system", "content": system},
        #           {"role": "user",   "content": user},
        #       ],
        #       text_format=ThreatPostResponse,
        #       max_output_tokens=self._max_output_tokens,
        #   )
        #   return response.output_parsed
        #
        # See OpenAI's structured-outputs docs for the current API shape.
        raise NotImplementedError(
            "OpenAI provider is a stub in v1. Wire the SDK call inside "
            "`generate_post()` and `cyberalertx.ai.generator` will pick it up "
            "with no other changes."
        )


__all__ = ["OpenAIProvider"]
