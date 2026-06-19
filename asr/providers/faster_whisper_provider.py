"""
Faster Whisper ASR Provider Implementation
"""
import os
import logging
from typing import Optional, List, Tuple
from faster_whisper import WhisperModel
from .base import ASRProvider, ProviderConfig

logger = logging.getLogger("asr.faster_whisper")

class FasterWhisperProvider(ASRProvider):
    """ASR provider using faster-whisper"""
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._model_instance = None
        self._model_name = config.model
        
    def _load_model(self):
        """Load the ASR model once and cache it"""
        if self._model_instance is None:
            try:
                logger.info(f"Loading ASR model: {self._model_name}")
                self._model_instance = WhisperModel(
                    self._model_name,
                    device="cuda" if os.getenv("CUDA_VISIBLE_DEVICES") else "cpu",
                    compute_type=self.config.compute_type,
                    download_root=os.getenv("ASR_MODEL_CACHE", "/app/models")
                )
                logger.info("ASR model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load ASR model: {e}")
                raise
        return self._model_instance
    
    def transcribe(self, file_path: str, language: Optional[str] = None, 
                   use_alignment: bool = False) -> Tuple[str, List[dict], List[dict]]:
        """
        Transcribe audio file using faster-whisper
        
        Args:
            file_path: Path to audio file
            language: Language code (e.g., 'en', 'es')
            use_alignment: Whether to include word-level alignment
            
        Returns:
            Tuple of (text, segments, words)
        """
        try:
            # Load model if not already loaded
            model = self._load_model()
            
            # Perform transcription with forced alignment if available
            segments, info = model.transcribe(
                file_path,
                language=language,
                task="transcribe",
                beam_size=5,
                best_of=5,
                vad_filter=True,
                word_timestamps=use_alignment
            )
            
            # Convert segments to the expected format
            segments_list = []
            words_list = []
            
            # If we have word timestamps, we can extract them
            if hasattr(info, 'words') and info.words:
                # Process word-level timestamps
                for word in info.words:
                    words_list.append({
                        "text": word.word,
                        "start_ms": int(word.start * 1000),
                        "end_ms": int(word.end * 1000),
                        "confidence": getattr(word, 'probability', None)
                    })
            
            # Process segments (transcript segments)
            for segment in segments:
                segments_list.append({
                    "start_ms": int(segment.start * 1000),
                    "end_ms": int(segment.end * 1000),
                    "text": segment.text
                })
            
            # Get the full text
            full_text = " ".join([seg["text"] for seg in segments_list])
            
            # Determine if forced alignment was used
            forced_alignment_used = use_alignment and (hasattr(info, 'words') and info.words)
            
            return full_text, segments_list, words_list
            
        except Exception as e:
            logger.error(f"Error processing audio file: {e}")
            raise
    
    def get_model_info(self) -> dict:
        """Get information about the model being used"""
        return {
            "name": "faster-whisper",
            "model": self._model_name,
            "compute_type": self.config.compute_type,
            "force_alignment": self.config.force_alignment
        }
    
    def is_available(self) -> bool:
        """Check if faster-whisper provider is available"""
        try:
            # Try to import faster_whisper
            import faster_whisper
            return True
        except ImportError:
            return False