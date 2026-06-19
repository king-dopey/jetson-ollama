"""
Base ASR Provider Interface
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
from pydantic import BaseModel

class ASRProvider(ABC):
    """Abstract base class for ASR providers"""
    
    @abstractmethod
    def transcribe(self, file_path: str, language: Optional[str] = None, 
                   use_alignment: bool = False) -> Tuple[str, List[dict], List[dict]]:
        """
        Transcribe audio file and return text, segments, and words
        
        Args:
            file_path: Path to audio file
            language: Language code (e.g., 'en', 'es')
            use_alignment: Whether to include word-level alignment
            
        Returns:
            Tuple of (text, segments, words)
        """
        pass
    
    @abstractmethod
    def get_model_info(self) -> dict:
        """Get information about the model being used"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available"""
        pass

class ProviderConfig(BaseModel):
    """Configuration for ASR provider"""
    name: str
    model: str
    accuracy_model: str
    compute_type: str
    force_alignment: bool
    diarization_enabled: bool
    lazy_load_alignment: bool