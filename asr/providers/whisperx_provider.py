"""
WhisperX ASR Provider Implementation
"""
import os
import logging
from typing import Any, Optional, List, Tuple, Iterable
from cache_config import get_model_cache_dir
from .base import ASRProvider, ProviderConfig
from .model_names import (
    DEFAULT_WHISPER_PROVIDER_MODELS,
    normalize_and_validate_whisperx_model_name,
)

logger = logging.getLogger("asr.whisperx")


def _format_stage_error(stage: str, exc: Exception) -> RuntimeError:
    message = f"WhisperX stage '{stage}' failed: {exc}"
    if "set_audio_backend" in str(exc) or "get_audio_backend" in str(exc):
        message += (
            " (dependency API compatibility issue: torchaudio backend selector API "
            "is missing; verify torchaudio/pyannote versions)"
        )
    return RuntimeError(message)


class WhisperXProvider(ASRProvider):
    """ASR provider using WhisperX for alignment"""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._default_model_name = config.model
        self._default_accuracy_model_name = config.accuracy_model
        self._whisperx_module = None
        self._model_instances: dict[str, Any] = {}
        self._supported_model_names: tuple[str, ...] | None = None
        # WhisperX align models are language-specific.
        self._alignment_models: dict[str, tuple[Any, Any]] = {}
        self._device = (
            config.resolved_device
            or ("cuda" if os.getenv("CUDA_VISIBLE_DEVICES") else "cpu")
        )
        self._compute_type = config.resolved_compute_type or config.compute_type

    @staticmethod
    def _ensure_torchaudio_backend_compat() -> None:
        """Provide backward-compatible torchaudio backend APIs when removed upstream."""
        try:
            import torchaudio
        except Exception as exc:
            logger.debug("torchaudio import failed while preparing compatibility shims: %s", exc)
            return

        if not hasattr(torchaudio, "set_audio_backend"):
            torchaudio.set_audio_backend = lambda _backend=None: None
        if not hasattr(torchaudio, "get_audio_backend"):
            torchaudio.get_audio_backend = lambda: None

    def _import_whisperx(self):
        if self._whisperx_module is not None:
            return self._whisperx_module
        self._ensure_torchaudio_backend_compat()
        try:
            import whisperx
            self._whisperx_module = whisperx
            return self._whisperx_module
        except Exception as exc:
            logger.error("WhisperX import failed: %s", exc)
            raise _format_stage_error("dependency_import", exc) from exc

    def _get_supported_model_names(self) -> tuple[str, ...]:
        if self._supported_model_names is not None:
            return self._supported_model_names
        models: set[str] = set(DEFAULT_WHISPER_PROVIDER_MODELS)
        whisperx = self._import_whisperx()
        candidates: list[Iterable[str] | None] = [
            getattr(whisperx, "available_models", None),
            getattr(whisperx, "AVAILABLE_MODELS", None),
            getattr(whisperx, "_MODELS", None),
        ]
        for candidate in candidates:
            values = candidate() if callable(candidate) else candidate
            if isinstance(values, (list, tuple, set)):
                models.update(str(item) for item in values)
        self._supported_model_names = tuple(sorted(models))
        return self._supported_model_names

    def _resolve_model_name(self, requested_model_name: Optional[str]) -> str:
        selected_model = requested_model_name or self._default_model_name
        resolution = normalize_and_validate_whisperx_model_name(
            selected_model,
            supported_models=self._get_supported_model_names(),
        )
        if resolution.alias_applied:
            logger.info(
                "Normalized public model alias '%s' to WhisperX provider model '%s'",
                resolution.received,
                resolution.normalized,
            )
        return resolution.normalized

    def _load_model(self, requested_model_name: Optional[str] = None):
        """Load and cache the WhisperX transcription model."""
        model_name = self._resolve_model_name(requested_model_name)
        if model_name not in self._model_instances:
            try:
                logger.info("Loading WhisperX base model: %s", model_name)
                whisperx = self._import_whisperx()
                self._model_instances[model_name] = whisperx.load_model(
                    model_name,
                    device=self._device,
                    compute_type=self._compute_type,
                    download_root=get_model_cache_dir(),
                )
                logger.info("WhisperX base model loaded successfully")
            except Exception as exc:
                raise _format_stage_error("model_load", exc) from exc
        return self._model_instances[model_name]
        
    def _load_alignment_model(self, language: str = "en"):
        """Load alignment model for specific language"""
        if language not in self._alignment_models:
            try:
                logger.info("Loading WhisperX alignment model for language: %s", language)
                whisperx = self._import_whisperx()
                
                # Load alignment model for the specific language
                self._alignment_models[language] = whisperx.load_align_model(
                    language_code=language,
                    device=self._device,
                )
                logger.info("WhisperX alignment model loaded successfully for %s", language)
            except Exception as exc:
                logger.error("Failed to load WhisperX alignment model for %s: %s", language, exc)
                raise _format_stage_error("alignment_model_load", exc) from exc
        return self._alignment_models[language]
    
    def transcribe(
        self,
        file_path: str,
        language: Optional[str] = None,
        use_alignment: bool = False,
        model_name: Optional[str] = None,
        accuracy_model_name: Optional[str] = None,
    ) -> Tuple[str, List[dict], List[dict]]:
        """
        Transcribe audio file using WhisperX
        
        Args:
            file_path: Path to audio file
            language: Language code (e.g., 'en', 'es')
            use_alignment: Whether to include word-level alignment
            model_name: Optional transcription model override
            accuracy_model_name: Optional accuracy model override
            
        Returns:
            Tuple of (text, segments, words)
        """
        try:
            whisperx = self._import_whisperx()
            if use_alignment:
                selected_model = accuracy_model_name or self._default_accuracy_model_name or model_name
            else:
                selected_model = model_name
            model = self._load_model(selected_model)
            
            # Load audio
            try:
                audio = whisperx.load_audio(file_path)
            except Exception as exc:
                raise _format_stage_error("audio_load", exc) from exc
            
            # Transcribe
            try:
                result = model.transcribe(audio, language=language)
            except Exception as exc:
                raise _format_stage_error("transcription", exc) from exc

            segments = result.get("segments", [])

            # WhisperX alignment is a dedicated post-transcription stage.
            if use_alignment and segments:
                try:
                    alignment_language = result.get("language") or language or "en"
                    model_a, metadata = self._load_alignment_model(alignment_language)
                    aligned = whisperx.align(
                        segments,
                        model_a,
                        metadata,
                        audio,
                        self._device,
                        return_char_alignments=False,
                    )
                    segments = aligned.get("segments", segments)
                except Exception as exc:
                    raise _format_stage_error("alignment", exc) from exc

            # Extract segments and words
            segments_list = []
            words_list = []
            
            # Process segments and words
            for segment in segments:
                segments_list.append(
                    {
                        "start_ms": int(segment.get("start", 0) * 1000),
                        "end_ms": int(segment.get("end", 0) * 1000),
                        "text": segment.get("text", ""),
                    }
                )

                for word in segment.get("words", []) or []:
                    word_start = word.get("start")
                    word_end = word.get("end")
                    if word_start is None or word_end is None:
                        continue
                    words_list.append(
                        {
                            "text": word.get("word", ""),
                            "start_ms": int(word_start * 1000),
                            "end_ms": int(word_end * 1000),
                            "confidence": word.get("confidence", None),
                        }
                    )
            
            # Get the full text
            full_text = " ".join(seg["text"] for seg in segments_list).strip()
            
            return full_text, segments_list, words_list
            
        except Exception as exc:
            logger.error("Error processing audio file with WhisperX: %s", exc)
            raise
    
    def get_model_info(self) -> dict:
        """Get information about the model being used"""
        return {
            "name": "whisperx",
            "model": self._default_model_name,
            "device": self._device,
            "compute_type": self._compute_type,
            "force_alignment": self.config.force_alignment,
            "diarization_enabled": self.config.diarization_enabled,
            "degraded": self.config.degraded,
            "degradation_reason": self.config.degradation_reason,
        }
    
    def is_available(self) -> bool:
        """Check if WhisperX provider is available"""
        try:
            # Try to import whisperx
            import whisperx
            return True
        except ImportError:
            return False
