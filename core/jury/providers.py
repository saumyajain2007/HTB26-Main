"""Jury model clients for Google Gemini and Vultr Serverless Inference.

Both providers expose an OpenAI-compatible chat API, so one small client serves
them. `ProviderModel` is the `model_call(model, prompt, temperature)` the jury
runner takes: it routes by a provider prefix on the model ID, so one jury can mix
families from different providers.

    gemini:gemini-2.5-pro       Google Gemini         (GEMINI_API_KEY)
    vultr:<model id>            Vultr Inference       (VULTR_INFERENCE_API_KEY)
    cortex:<model id>           Snowflake Cortex      (SNOWFLAKE_ACCOUNT, SNOWFLAKE_PAT)

Nothing here is scientific judgement; it only moves a prompt to a model and the
reply back, as `CortexModel` does.
"""

from __future__ import annotations

import math
import os

from .client import RESPONSE_FORMAT, CortexModel, ModelReply

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
VULTR_BASE_URL = "https://api.vultrinference.com/v1"
PROVIDERS = ("gemini", "vultr", "cortex")
MAX_OUTPUT_TOKENS = 32768


def split_model_id(model: str) -> tuple[str, str]:
    """`gemini:gemini-2.5-pro` -> (`gemini`, `gemini-2.5-pro`)."""
    provider, sep, name = model.partition(":")
    if not sep or provider not in PROVIDERS or not name:
        raise ValueError(
            f"Model ID {model!r} needs a provider prefix: one of {', '.join(PROVIDERS)} "
            "(for example gemini:gemini-2.5-pro)"
        )
    return provider, name


class OpenAICompatModel:
    """One chat-completions request per attempt; the jury runner owns retries."""

    def __init__(self, *, api_key_env: str, base_url: str, json_schema: bool, timeout=None):
        from openai import OpenAI

        key = os.environ.get(api_key_env, "")
        if not key:
            raise ValueError(f"Set {api_key_env}")
        timeout = float(os.environ.get("JURY_TIMEOUT_SECONDS", "120") if timeout is None else timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Request timeout must be a positive finite number of seconds")
        self.client = OpenAI(api_key=key, base_url=base_url, max_retries=0, timeout=timeout)
        # Gemini accepts a JSON schema. Vultr's models vary, so ask for a JSON object and let
        # the jury's own validation (which every provider's reply goes through) do the checking.
        self.response_format = RESPONSE_FORMAT if json_schema else {"type": "json_object"}

    def __call__(self, model: str, prompt: str, temperature: float) -> ModelReply:
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format=self.response_format,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        choice = response.choices[0]
        usage = response.usage
        return ModelReply(
            choice.message.content,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            MAX_OUTPUT_TOKENS,
            choice.finish_reason,
        )

    def close(self) -> None:
        self.client.close()


class ProviderModel:
    """Routes each call to the provider named by the model ID's prefix.

    A client is built the first time its provider is used, so a jury needs only the
    credentials of the providers it names.
    """

    def __init__(self, reasoning_effort: dict[str, str] | None = None):
        self._reasoning_effort = reasoning_effort or {}
        self._clients: dict[str, object] = {}

    def _client(self, provider: str):
        if provider not in self._clients:
            if provider == "gemini":
                self._clients[provider] = OpenAICompatModel(
                    api_key_env="GEMINI_API_KEY", base_url=GEMINI_BASE_URL, json_schema=True
                )
            elif provider == "vultr":
                self._clients[provider] = OpenAICompatModel(
                    api_key_env="VULTR_INFERENCE_API_KEY",
                    base_url=os.environ.get("VULTR_INFERENCE_BASE_URL", VULTR_BASE_URL),
                    json_schema=False,
                )
            else:
                self._clients[provider] = CortexModel(
                    reasoning_effort={
                        split_model_id(m)[1]: e
                        for m, e in self._reasoning_effort.items()
                        if m.startswith("cortex:")
                    }
                )
        return self._clients[provider]

    def __call__(self, model: str, prompt: str, temperature: float):
        provider, name = split_model_id(model)
        return self._client(provider)(name, prompt, temperature)

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
