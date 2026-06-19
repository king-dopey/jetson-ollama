"""
Model-name normalization and validation helpers for ASR providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


PUBLIC_TO_PROVIDER_MODEL_ALIASES: dict[str, str] = {
    "whisper-large-v3-turbo": "large-v3-turbo",
    "whisper-large-v3": "large-v3",
}

# Canonical Whisper model sizes accepted by WhisperX/faster-whisper style loaders.
DEFAULT_WHISPER_PROVIDER_MODELS: tuple[str, ...] = (
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v1",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
    "turbo",
)


@dataclass(frozen=True)
class ModelResolution:
    received: str
    normalized: str
    alias_applied: bool


class UnsupportedWhisperXModelError(ValueError):
    pass


def normalize_public_model_alias(model_name: str) -> ModelResolution:
    received = (model_name or "").strip()
    if not received:
        raise ValueError("model name must be a non-empty string")
    normalized = PUBLIC_TO_PROVIDER_MODEL_ALIASES.get(received, received)
    return ModelResolution(
        received=received,
        normalized=normalized,
        alias_applied=(normalized != received),
    )


def _looks_like_model_repo_id(model_name: str) -> bool:
    # Keep compatibility for custom Hugging Face repo IDs and local model paths.
    return "/" in model_name or ":" in model_name


def normalize_and_validate_whisperx_model_name(
    model_name: str,
    supported_models: Iterable[str] | None = None,
) -> ModelResolution:
    resolution = normalize_public_model_alias(model_name)
    models = tuple(sorted(set(supported_models or DEFAULT_WHISPER_PROVIDER_MODELS)))
    if resolution.normalized in models or _looks_like_model_repo_id(resolution.normalized):
        return resolution

    supported = ", ".join(models)
    raise UnsupportedWhisperXModelError(
        "Unsupported WhisperX model name: "
        f"received='{resolution.received}', "
        f"normalized='{resolution.normalized}', "
        f"supported provider models=[{supported}]"
    )
