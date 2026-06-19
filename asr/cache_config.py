"""
ASR model cache configuration and startup validation.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass


DEFAULT_ASR_MODEL_CACHE = "/app/models"


@dataclass(frozen=True)
class CachePaths:
    model_cache: str
    hf_home: str
    huggingface_hub_cache: str
    transformers_cache: str
    xdg_cache_home: str


def _abspath(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.abspath(os.path.join(cwd, path)))


def resolve_cache_paths(env: dict[str, str] | None = None, cwd: str | None = None) -> CachePaths:
    source_env = env if env is not None else os.environ
    base_dir = cwd or os.getcwd()

    model_cache = _abspath(source_env.get("ASR_MODEL_CACHE", DEFAULT_ASR_MODEL_CACHE), base_dir)
    hf_home = _abspath(source_env.get("HF_HOME", os.path.join(model_cache, "hf")), base_dir)
    huggingface_hub_cache = _abspath(
        source_env.get("HUGGINGFACE_HUB_CACHE", os.path.join(hf_home, "hub")),
        base_dir,
    )
    transformers_cache = _abspath(
        source_env.get("TRANSFORMERS_CACHE", os.path.join(hf_home, "transformers")),
        base_dir,
    )
    xdg_cache_home = _abspath(
        source_env.get("XDG_CACHE_HOME", os.path.join(model_cache, "xdg")),
        base_dir,
    )

    return CachePaths(
        model_cache=model_cache,
        hf_home=hf_home,
        huggingface_hub_cache=huggingface_hub_cache,
        transformers_cache=transformers_cache,
        xdg_cache_home=xdg_cache_home,
    )


def apply_cache_environment(paths: CachePaths, env: dict[str, str] | None = None) -> None:
    target = env if env is not None else os.environ
    target["ASR_MODEL_CACHE"] = paths.model_cache
    target["HF_HOME"] = paths.hf_home
    target["HUGGINGFACE_HUB_CACHE"] = paths.huggingface_hub_cache
    target["TRANSFORMERS_CACHE"] = paths.transformers_cache
    target["XDG_CACHE_HOME"] = paths.xdg_cache_home


def validate_writable_directory(path: str, label: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path, delete=True, prefix=".asr-cache-probe-") as probe:
            probe.write("ok")
            probe.flush()
    except OSError as exc:
        uid = getattr(os, "getuid", lambda: -1)()
        gid = getattr(os, "getgid", lambda: -1)()
        raise RuntimeError(
            f"asr_model_cache_not_writable: label={label} path='{path}' uid={uid} gid={gid} error={exc}"
        ) from exc


def initialize_cache_environment(logger: logging.Logger | None = None) -> CachePaths:
    paths = resolve_cache_paths()
    apply_cache_environment(paths)

    validate_writable_directory(paths.model_cache, "asr_model_cache")
    validate_writable_directory(paths.hf_home, "hf_home")
    validate_writable_directory(paths.huggingface_hub_cache, "huggingface_hub_cache")
    validate_writable_directory(paths.transformers_cache, "transformers_cache")
    validate_writable_directory(paths.xdg_cache_home, "xdg_cache_home")

    if logger is not None:
        logger.info(
            "ASR cache paths configured: ASR_MODEL_CACHE=%s HF_HOME=%s HUGGINGFACE_HUB_CACHE=%s "
            "TRANSFORMERS_CACHE=%s XDG_CACHE_HOME=%s",
            paths.model_cache,
            paths.hf_home,
            paths.huggingface_hub_cache,
            paths.transformers_cache,
            paths.xdg_cache_home,
        )
    return paths


def get_model_cache_dir() -> str:
    return resolve_cache_paths().model_cache
