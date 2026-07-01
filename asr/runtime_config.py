"""ASR runtime backend and compute-type resolution."""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_SUPPORTED_COMPUTE_TYPES = {
    "cpu": {"float32", "int8", "int8_float32"},
    "cuda": {"float16", "float32", "bfloat16", "int8", "int8_float16", "int8_float32"},
}

_DEFAULT_COMPUTE_FOR_DEVICE = {
    "cpu": "float32",
    "cuda": "float16",
}


class RuntimeResolutionError(RuntimeError):
    """Raised when ASR runtime configuration is incompatible with the backend."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        self.code = code
        self.details = dict(details or {})
        detail_blob = " ".join(f"{k}={v}" for k, v in sorted(self.details.items()))
        full_message = f"{code}: {message}".strip()
        if detail_blob:
            full_message = f"{full_message} ({detail_blob})"
        super().__init__(full_message)


@dataclass(frozen=True)
class RuntimeResolution:
    requested_device: str
    requested_compute_type: str
    resolved_device: str
    resolved_compute_type: str
    cuda_available: bool
    degraded: bool
    degradation_reason: str | None
    expected_device: str
    diagnostics: dict[str, Any]
    cuda_compat_mode: str  # "strict" | "fallback" | "disabled"

    def health_payload(self) -> dict[str, Any]:
        return {
            "requested_device": self.requested_device,
            "requested_compute_type": self.requested_compute_type,
            "resolved_device": self.resolved_device,
            "resolved_compute_type": self.resolved_compute_type,
            "cuda_available": self.cuda_available,
            "degraded": self.degraded,
            "degradation_reason": self.degradation_reason,
            "expected_device": self.expected_device,
            "diagnostics": self.diagnostics,
            "cuda_compat_mode": self.cuda_compat_mode,
        }


@dataclass(frozen=True)
class TorchBackendInfo:
    import_ok: bool
    version: str
    cuda_available: bool
    cuda_version: str | None
    device_count: int


@dataclass(frozen=True)
class CTranslate2Info:
    import_ok: bool
    version: str
    cuda_supported: bool | None


def _to_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_device(value: str | None, *, default: str = "auto") -> str:
    raw = (value or default).strip().lower()
    alias_map = {
        "gpu": "cuda",
        "cuda": "cuda",
        "cpu": "cpu",
        "auto": "auto",
    }
    if raw not in alias_map:
        raise RuntimeResolutionError(
            "asr_invalid_device_request",
            "ASR_DEVICE must be one of: auto, cuda, cpu",
            details={"received": raw},
        )
    return alias_map[raw]


def _import_optional(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def _detect_torch_backend() -> TorchBackendInfo:
    torch = _import_optional("torch")
    if torch is None:
        return TorchBackendInfo(
            import_ok=False,
            version="unavailable",
            cuda_available=False,
            cuda_version=None,
            device_count=0,
        )

    cuda_available = False
    device_count = 0
    try:
        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
    except Exception:
        cuda_available = False
        device_count = 0

    return TorchBackendInfo(
        import_ok=True,
        version=str(getattr(torch, "__version__", "unknown")),
        cuda_available=cuda_available,
        cuda_version=getattr(torch.version, "cuda", None),
        device_count=device_count,
    )


def _detect_ctranslate2_backend() -> CTranslate2Info:
    ctranslate2 = _import_optional("ctranslate2")
    if ctranslate2 is None:
        return CTranslate2Info(import_ok=False, version="unavailable", cuda_supported=None)

    cuda_supported: bool | None = None
    try:
        get_supported = getattr(ctranslate2, "get_supported_compute_types", None)
        if callable(get_supported):
            supported_cuda = get_supported("cuda")
            cuda_supported = bool(supported_cuda)
    except Exception:
        cuda_supported = None

    return CTranslate2Info(
        import_ok=True,
        version=str(getattr(ctranslate2, "__version__", "unknown")),
        cuda_supported=cuda_supported,
    )


def _detect_cuda_compat_mode() -> str:
    """Detect CUDA compatibility mode from environment."""
    mode = os.getenv("ASR_CUDA_COMPAT_MODE", "fallback")
    if mode not in ("strict", "fallback", "disabled"):
        logger.warning("Unknown ASR_CUDA_COMPAT_MODE=%s, defaulting to fallback", mode)
        return "fallback"
    return mode


def _verify_ctranslate2_cuda() -> bool:
    """Verify CTranslate2 CUDA support by attempting a minimal CUDA operation."""
    try:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types("cuda")
        return len(supported) > 0
    except Exception:
        return False


def resolve_runtime(env: Mapping[str, str] | None = None) -> RuntimeResolution:
    runtime_env = dict(os.environ if env is None else env)

    requested_device = _normalize_device(runtime_env.get("ASR_DEVICE"), default="auto")
    expected_device = _normalize_device(runtime_env.get("ASR_EXPECT_DEVICE"), default="auto")
    requested_compute_type = (runtime_env.get("ASR_COMPUTE_TYPE") or "float16").strip().lower()
    strict_expected_cuda = expected_device == "cuda"
    allow_compute_fallback = _to_bool(
        runtime_env.get("ASR_ALLOW_COMPUTE_FALLBACK"),
        default=not strict_expected_cuda,
    )
    allow_degraded_backend = _to_bool(
        runtime_env.get("ASR_ALLOW_DEGRADED_BACKEND"),
        default=not strict_expected_cuda,
    )
    cuda_compat_mode = _detect_cuda_compat_mode()

    torch_info = _detect_torch_backend()
    ct2_info = _detect_ctranslate2_backend()

    resolved_device = requested_device
    if requested_device == "auto":
        resolved_device = "cuda" if torch_info.cuda_available else "cpu"

    if requested_device == "cuda" and not torch_info.cuda_available:
        raise RuntimeResolutionError(
            "asr_cuda_requested_but_unavailable",
            "ASR requested device=cuda but torch cannot access CUDA",
            details={
                "torch_version": torch_info.version,
                "torch_cuda": torch_info.cuda_version,
                "cuda_available": torch_info.cuda_available,
            },
        )

    degraded = False
    degradation_reason: str | None = None

    # Check CTranslate2 CUDA support with compatibility mode
    if cuda_compat_mode == "fallback" and resolved_device == "cuda":
        if not _verify_ctranslate2_cuda():
            degraded = True
            degradation_reason = "ctranslate2-cuda-abi-mismatch"
            resolved_device = "cpu"

    if expected_device == "cuda" and resolved_device != "cuda":
        if not allow_degraded_backend:
            raise RuntimeResolutionError(
                "asr_cuda_unavailable_on_orin_deployment",
                "Expected GPU-backed ASR (ASR_EXPECT_DEVICE=cuda) but resolved backend is CPU",
                details={
                    "torch_version": torch_info.version,
                    "torch_cuda": torch_info.cuda_version,
                    "cuda_available": torch_info.cuda_available,
                    "requested_device": requested_device,
                    "resolved_device": resolved_device,
                },
            )
        degraded = True
        degradation_reason = "asr_cuda_unavailable_on_orin_deployment"

    supported_compute_types = _SUPPORTED_COMPUTE_TYPES[resolved_device]
    resolved_compute_type = requested_compute_type
    if requested_compute_type not in supported_compute_types:
        if not allow_compute_fallback:
            raise RuntimeResolutionError(
                "asr_compute_type_unsupported_for_backend",
                "Requested compute type is incompatible with resolved backend",
                details={
                    "requested_compute_type": requested_compute_type,
                    "resolved_device": resolved_device,
                    "supported": sorted(supported_compute_types),
                },
            )
        resolved_compute_type = _DEFAULT_COMPUTE_FOR_DEVICE[resolved_device]
        degraded = True
        degradation_reason = degradation_reason or "asr_compute_type_unsupported_for_backend"

    diagnostics = {
        "torch": {
            "import_ok": torch_info.import_ok,
            "version": torch_info.version,
            "cuda_version": torch_info.cuda_version,
            "cuda_available": torch_info.cuda_available,
            "cuda_device_count": torch_info.device_count,
            "cpu_build_detected": "+cpu" in torch_info.version,
        },
        "ctranslate2": {
            "import_ok": ct2_info.import_ok,
            "version": ct2_info.version,
            "cuda_supported": ct2_info.cuda_supported,
        },
        "nvidia_runtime_env": {
            "NVIDIA_VISIBLE_DEVICES": runtime_env.get("NVIDIA_VISIBLE_DEVICES", "<unset>"),
            "NVIDIA_DRIVER_CAPABILITIES": runtime_env.get("NVIDIA_DRIVER_CAPABILITIES", "<unset>"),
            "CUDA_VISIBLE_DEVICES": runtime_env.get("CUDA_VISIBLE_DEVICES", "<unset>"),
        },
        "flags": {
            "allow_compute_fallback": allow_compute_fallback,
            "allow_degraded_backend": allow_degraded_backend,
        },
    }

    return RuntimeResolution(
        requested_device=requested_device,
        requested_compute_type=requested_compute_type,
        resolved_device=resolved_device,
        resolved_compute_type=resolved_compute_type,
        cuda_available=torch_info.cuda_available,
        degraded=degraded,
        degradation_reason=degradation_reason,
        expected_device=expected_device,
        diagnostics=diagnostics,
        cuda_compat_mode=cuda_compat_mode,
    )
