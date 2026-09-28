"""Errors raised by the model layer (ARCHITECTURE.md D4, D6, D7).

Transport errors are the only retryable ones (D6). Every other error here is a hard error: the
run aborts and an ``error`` event is written (D7).
"""


class LLMError(RuntimeError):
    """Base class for model-layer errors."""


class TransportError(LLMError):
    """Connection refused, HTTP 5xx or a timeout. Retried up to twice with the same seed (D6)."""


class ServerError(LLMError):
    """Any other non-OK response from the runtime, or a response that does not parse."""


class DigestMismatchError(LLMError):
    """The runtime's model digest differs from ``configs/stack.yaml``. Never update the pin."""


class TokenizerError(LLMError):
    """The tokenizer files are missing, or were not downloaded at the pinned revision."""


class ContextOverflowError(LLMError):
    """Pre-flight: ``prompt_tokens + num_predict > num_ctx`` (D4 §Truncation, 1)."""


class TruncationError(LLMError):
    """The reported prompt count is below the post-check's lower bound (D4 §Truncation, 2)."""


class TokenizerMismatchError(LLMError):
    """The runtime counted more prompt tokens than the local tokenizer, or a cold probe
    disagreed with it (A-018)."""


class CalibrationError(LLMError):
    """The token calibration could not classify the runtime or a probe failed its check (D4)."""


class CalibrationMissingError(LLMError):
    """``reports/token_calibration.json`` is missing, stale or invalid (D4 §Before calibration)."""
