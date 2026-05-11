"""Concrete LLM providers.

Public surface kept narrow — callers go through `cyberalertx.ai.ContentGenerator`,
not directly through these classes.
"""
from .anthropic_provider import AnthropicProvider
from .openai_stub import OpenAIProvider

__all__ = ["AnthropicProvider", "OpenAIProvider"]
