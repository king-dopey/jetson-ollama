"""
WhisperX ASR Provider Implementation
"""
import os
import logging
from typing import Optional, List, Tuple
from .base import ASRProvider, ProviderConfig

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
        self._alignment_model = None
        self._model_name = config.model
        self._alignment_models = {}  # Cache for alignment models by language

    @staticmethod
    def _ensure_torchaudio_backend_compat() -> None:
        """Provide backward-compatible torchaudio backend APIs when removed upstream."""
        try:
            import torchaudio
        except Exception as exc:
            logger.debug("torchaudio import failed while preparing compatibility shims: %s", exc)
            return

        shimmed = []

        if not hasattr(torchaudio, "set_audio_backend"):
            def _set_audio_backend(_backend: str | None = None) -> None:
                return None
            torchaudio.set_audio_backend = _set_audio_backend
            shimmed.append("set_audio_backend")

        if not hasattr(torchaudio, "get_audio_backend"):
            def _get_audio_backend() -> None:
                return None
            torchaudio.get_audio_backend = _get_audio_backend
            shimmed.append("get_audio_backend")

        if shimmed:
            logger.info(
                "Installed torchaudio compatibility shims: %s (torchaudio=%s)",
                ", ".join(shimmed),
                getattr(torchaudio, "__version__", "unknown"),
            )

    def _import_whisperx(self):
        self._ensure_torchaudio_backend_compat()
        try:
            import whisperx
            return whisperx
        except Exception as exc:
            logger.error("WhisperX import failed: %s", exc)
            raise _format_stage_error("dependency_import", exc) from exc
        
    def _load_alignment_model(self, language: str = "en"):
        """Load alignment model for specific language"""
        if language not in self._alignment_models:
            try:
                logger.info(f"Loading WhisperX alignment model for language: {language}")
                whisperx = self._import_whisperx()
                
                # Load alignment model for the specific language
                self._alignment_models[language] = whisperx.load_align_model(
                    language_code=language,
                    device="cuda" if os.getenv("CUDA_VISIBLE_DEVICES") else "cpu"
                )
                logger.info(f"WhisperX alignment model loaded successfully for {language}")
            except Exception as e:
                logger.error(f"Failed to load WhisperX alignment model for {language}: {e}")
                raise
        return self._alignment_models[language]
    
    def transcribe(self, file_path: str, language: Optional[str] = None, 
                   use_alignment: bool = False) -> Tuple[str, List[dict], List[dict]]:
        """
        Transcribe audio file using WhisperX
        
        Args:
            file_path: Path to audio file
            language: Language code (e.g., 'en', 'es')
            use_alignment: Whether to include word-level alignment
            
        Returns:
            Tuple of (text, segments, words)
        """
        try:
            whisperx = self._import_whisperx()
            
            # Load the base model
            try:
                logger.info(f"Loading WhisperX base model: {self._model_name}")
                model = whisperx.load_model(
                    self._model_name,
                    device="cuda" if os.getenv("CUDA_VISIBLE_DEVICES") else "cpu",
                    compute_type=self.config.compute_type,
                    download_root=os.getenv("ASR_MODEL_CACHE", "/app/models")
                )
            except Exception as exc:
                raise _format_stage_error("model_load", exc) from exc
            logger.info("WhisperX base model loaded successfully")
            
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
            
            # Extract segments and words
            segments_list = []
            words_list = []
            
            # Process segments and words
            if "segments" in result:
                for segment in result["segments"]:
                    segments_list.append({
                        "start_ms": int(segment.get("start", 0) * 1000),
                        "end_ms": int(segment.get("end", 0) * 1000),
                        "text": segment.get("text", "")
                    })
                    
                    # Process words if alignment is enabled
                    if use_alignment and "words" in segment:
                        for word in segment["words"]:
                            words_list.append({
                                "text": word.get("word", ""),
                                "start_ms": int(word.get("start", 0) * 1000),
                                "end_ms": int(word.get("end", 0) * 1000),
                                "confidence": word.get("confidence", None)
                            })
            
            # Get the full text
            full_text = " ".join([seg["text"] for seg in segments_list])
            
            # Determine if alignment was used
            forced_alignment_used = use_alignment and len(words_list) > 0
            
            return full_text, segments_list, words_list
            
        except Exception as e:
            logger.error(f"Error processing audio file with WhisperX: {e}")
            raise
    
    def get_model_info(self) -> dict:
        """Get information about the model being used"""
        return {
            "name": "whisperx",
            "model": self._model_name,
            "compute_type": self.config.compute_type,
            "force_alignment": self.config.force_alignment,
            "diarization_enabled": self.config.diarization_enabled
        }
    
    def is_available(self) -> bool:
        """Check if WhisperX provider is available"""
        try:
            # Try to import whisperx
            import whisperx
            return True
        except ImportError:
            return False
