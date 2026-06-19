import logging
import os
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cache_config import initialize_cache_environment
from providers.base import ASRProvider, ProviderConfig
from providers.faster_whisper_provider import FasterWhisperProvider
from providers.whisperx_provider import WhisperXProvider
from runtime_config import RuntimeResolutionError, resolve_runtime


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asr")

ASR_ENABLED = os.getenv("ASR_ENABLED", "0").lower() == "1"
ASR_PORT = int(os.getenv("ASR_PORT", "8000"))
ASR_DEFAULT_PROVIDER = os.getenv("ASR_DEFAULT_PROVIDER", "faster-whisper")
ASR_MODEL = os.getenv("ASR_MODEL", "whisper-large-v3-turbo")
ASR_MODEL_ACCURACY = os.getenv("ASR_MODEL_ACCURACY", "whisper-large-v3")
ASR_ENGLISH_THROUGHPUT_MODEL = os.getenv("ASR_ENGLISH_THROUGHPUT_MODEL", "distil-large-v3.5-ct2")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "float16")
ASR_DEVICE = os.getenv("ASR_DEVICE", "auto")
ASR_FORCE_ALIGNMENT = os.getenv("ASR_FORCE_ALIGNMENT", "1").lower() == "1"
ASR_DIARIZATION_ENABLED = os.getenv("ASR_DIARIZATION_ENABLED", "0").lower() == "1"
ASR_LAZY_LOAD_ALIGNMENT = os.getenv("ASR_LAZY_LOAD_ALIGNMENT", "1").lower() == "1"
ASR_KEEP_WARM = os.getenv("ASR_KEEP_WARM", "0").lower() == "1"
ASR_LOG_LEVEL = os.getenv("ASR_LOG_LEVEL", "info")

logger.setLevel(getattr(logging, ASR_LOG_LEVEL.upper()))
CACHE_PATHS = initialize_cache_environment(logger)
ASR_MODEL_CACHE = CACHE_PATHS.model_cache

try:
    ASR_RUNTIME = resolve_runtime()
except RuntimeResolutionError as exc:
    logger.error("ASR runtime validation failed: %s", exc)
    raise

logger.info(
    "ASR runtime resolved: requested_device=%s requested_compute=%s resolved_device=%s "
    "resolved_compute=%s cuda_available=%s degraded=%s degradation_reason=%s",
    ASR_RUNTIME.requested_device,
    ASR_RUNTIME.requested_compute_type,
    ASR_RUNTIME.resolved_device,
    ASR_RUNTIME.resolved_compute_type,
    ASR_RUNTIME.cuda_available,
    ASR_RUNTIME.degraded,
    ASR_RUNTIME.degradation_reason,
)
logger.info("ASR runtime diagnostics: %s", ASR_RUNTIME.diagnostics)

_providers: dict[tuple[str, str, str], ASRProvider] = {}


class AlignRequest(BaseModel):
    audio_path: Optional[str] = None
    media_path: Optional[str] = None
    model: Optional[str] = None
    model_override: Optional[str] = None
    model_accuracy: Optional[str] = None
    return_word_timestamps: Optional[bool] = True
    prefer_forced_alignment: Optional[bool] = True
    language: Optional[str] = None
    strict: Optional[bool] = False


class Word(BaseModel):
    text: str
    start_ms: int
    end_ms: int
    confidence: Optional[float] = None


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class AlignResponse(BaseModel):
    text: str
    language: str
    model: str
    provider: str
    forced_alignment_used: bool
    degraded: bool
    degradation_reason: Optional[str] = None
    segments: List[Segment]
    words: List[Word]


app = FastAPI(
    title="ASR + Word Alignment Service",
    description="Speech-to-text service with word-level timing extraction",
    version="1.0.0",
)


def get_provider(
    provider_name: str,
    model_name: Optional[str] = None,
    accuracy_model_name: Optional[str] = None,
) -> ASRProvider:
    """Get or create ASR provider instance."""
    global _providers

    resolved_model_name = model_name or ASR_MODEL
    resolved_accuracy_model_name = accuracy_model_name or ASR_MODEL_ACCURACY
    provider_key = (provider_name, resolved_model_name, resolved_accuracy_model_name)

    if provider_key not in _providers:
        config = ProviderConfig(
            name=provider_name,
            model=resolved_model_name,
            accuracy_model=resolved_accuracy_model_name,
            compute_type=ASR_COMPUTE_TYPE,
            device=ASR_DEVICE,
            resolved_device=ASR_RUNTIME.resolved_device,
            resolved_compute_type=ASR_RUNTIME.resolved_compute_type,
            degraded=ASR_RUNTIME.degraded,
            degradation_reason=ASR_RUNTIME.degradation_reason,
            force_alignment=ASR_FORCE_ALIGNMENT,
            diarization_enabled=ASR_DIARIZATION_ENABLED,
            lazy_load_alignment=ASR_LAZY_LOAD_ALIGNMENT,
        )

        if provider_name == "faster-whisper":
            _providers[provider_key] = FasterWhisperProvider(config)
        elif provider_name == "whisperx":
            _providers[provider_key] = WhisperXProvider(config)
        else:
            raise ValueError(f"Unknown provider: {provider_name}")

    return _providers[provider_key]


def process_audio_file(
    file_path: str,
    language: Optional[str] = None,
    provider_name: str = "faster-whisper",
    use_alignment: bool = False,
    model_name: Optional[str] = None,
    accuracy_model_name: Optional[str] = None,
) -> tuple[str, list[dict], list[dict], bool]:
    """Process audio file and return transcription with timing information."""
    try:
        provider = get_provider(provider_name, model_name=model_name, accuracy_model_name=accuracy_model_name)
        full_text, segments_list, words_list = provider.transcribe(
            file_path,
            language=language,
            use_alignment=use_alignment,
            model_name=model_name,
            accuracy_model_name=accuracy_model_name,
        )
        forced_alignment_used = use_alignment and len(words_list) > 0
        return full_text, segments_list, words_list, forced_alignment_used
    except Exception as exc:
        message = f"provider '{provider_name}' processing failed: {exc}"
        logger.error("Error processing audio file (%s): %s", provider_name, exc)
        raise RuntimeError(message) from exc


def _is_multipart(content_type: str) -> bool:
    return "multipart/form-data" in (content_type or "").lower()


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Health check endpoint."""
    loaded_provider_names = sorted(list({provider_name for provider_name, _, _ in _providers.keys()}))
    return JSONResponse(
        {
            "status": "ok",
            "enabled": ASR_ENABLED,
            "configured_providers": ["faster-whisper", "whisperx"],
            "loaded_providers": loaded_provider_names,
            "lazy_load_alignment": ASR_LAZY_LOAD_ALIGNMENT,
            "runtime": ASR_RUNTIME.health_payload(),
        }
    )


@app.post("/align")
async def align(request: Request):
    """Align audio to text with word-level timing."""
    try:
        content_type = request.headers.get("content-type", "")
        upload: UploadFile | None = None
        payload_dict: dict[str, object] = {}

        if _is_multipart(content_type):
            form = await request.form()
            upload_obj = form.get("media_file") or form.get("file")
            if upload_obj is not None and hasattr(upload_obj, "read"):
                upload = upload_obj
            elif upload_obj is not None:
                raise HTTPException(status_code=400, detail="multipart media_file/file must be an uploaded file")
            payload_dict = {
                "audio_path": form.get("audio_path"),
                "media_path": form.get("media_path"),
                "model": form.get("model"),
                "model_override": form.get("model_override"),
                "model_accuracy": form.get("model_accuracy"),
                "return_word_timestamps": form.get("return_word_timestamps"),
                "prefer_forced_alignment": form.get("prefer_forced_alignment"),
                "language": form.get("language"),
                "strict": form.get("strict"),
            }
        else:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="JSON body must be an object")
            payload_dict = payload

        align_request = AlignRequest(**payload_dict)

        if upload is None and not align_request.audio_path and not align_request.media_path:
            raise HTTPException(
                status_code=400,
                detail="One of uploaded media_file/file, audio_path, or media_path must be provided",
            )

        temp_file_path = None
        try:
            if upload is not None:
                logger.info("ASR /align using uploaded media_file payload")
                temp_file_path = os.path.join("/tmp", f"asr_upload_{uuid.uuid4()}.tmp")
                with open(temp_file_path, "wb") as buffer:
                    buffer.write(await upload.read())
                file_path = temp_file_path
            elif align_request.audio_path:
                logger.warning("ASR /align using audio_path fallback (shared filesystem required)")
                file_path = align_request.audio_path
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=400, detail=f"Audio file not found: {file_path}")
                if not os.path.isfile(file_path):
                    raise HTTPException(status_code=400, detail=f"Audio path is not a file: {file_path}")
            elif align_request.media_path:
                logger.warning("ASR /align using media_path fallback (shared filesystem required)")
                file_path = align_request.media_path
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=400, detail=f"Media file not found: {file_path}")
                if not os.path.isfile(file_path):
                    raise HTTPException(status_code=400, detail=f"Media path is not a file: {file_path}")
            else:
                raise HTTPException(status_code=400, detail="No media provided")

            prefer_forced_alignment = bool(align_request.prefer_forced_alignment)
            return_word_timestamps = bool(align_request.return_word_timestamps)
            use_alignment = bool(ASR_FORCE_ALIGNMENT and prefer_forced_alignment and return_word_timestamps)
            provider_name = "whisperx" if use_alignment else ASR_DEFAULT_PROVIDER
            requested_model_name = align_request.model_override or align_request.model or ASR_MODEL
            requested_accuracy_model_name = align_request.model_accuracy or ASR_MODEL_ACCURACY

            full_text, segments, words, forced_alignment_used = process_audio_file(
                file_path,
                align_request.language,
                provider_name=provider_name,
                use_alignment=use_alignment,
                model_name=requested_model_name,
                accuracy_model_name=requested_accuracy_model_name,
            )

            if (align_request.strict or prefer_forced_alignment) and not forced_alignment_used:
                raise HTTPException(
                    status_code=400,
                    detail="Forced alignment required but not available",
                )

            response = AlignResponse(
                text=full_text,
                language=align_request.language or "en",
                model=requested_model_name,
                provider=provider_name,
                forced_alignment_used=forced_alignment_used,
                degraded=False,
                degradation_reason=None,
                segments=segments,
                words=words if return_word_timestamps else [],
            )
            return response
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error in align endpoint: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/models")
async def list_models() -> JSONResponse:
    """List available models."""
    return JSONResponse(
        {
            "models": [ASR_MODEL, ASR_MODEL_ACCURACY, ASR_ENGLISH_THROUGHPUT_MODEL],
            "default": ASR_MODEL,
            "accuracy_override": ASR_MODEL_ACCURACY,
            "english_throughput": ASR_ENGLISH_THROUGHPUT_MODEL,
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=ASR_PORT)
