import os
import logging
import asyncio
import json
import uuid
from typing import Optional, List, Dict, Any
from pathlib import Path
import tempfile
import shutil

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import whisper
from faster_whisper import WhisperModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asr")

# ASR configuration from environment variables
ASR_ENABLED = os.getenv("ASR_ENABLED", "0").lower() == "1"
ASR_PORT = int(os.getenv("ASR_PORT", "8000"))
ASR_MODEL = os.getenv("ASR_MODEL", "whisper-large-v3-turbo")
ASR_MODEL_ACCURACY = os.getenv("ASR_MODEL_ACCURACY", "whisper-large-v3")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "float16")
ASR_FORCE_ALIGNMENT = os.getenv("ASR_FORCE_ALIGNMENT", "1").lower() == "1"
ASR_KEEP_WARM = os.getenv("ASR_KEEP_WARM", "0").lower() == "1"
ASR_MODEL_CACHE = os.getenv("ASR_MODEL_CACHE", "/app/models")
ASR_LOG_LEVEL = os.getenv("ASR_LOG_LEVEL", "info")

# Set log level
logger.setLevel(getattr(logging, ASR_LOG_LEVEL.upper()))

# Global model instance for caching
_model_instance = None

# Pydantic models for request/response
class AlignRequest(BaseModel):
    media_path: Optional[str] = None
    media_file: Optional[UploadFile] = None
    model_override: Optional[str] = None
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

# FastAPI app
app = FastAPI(
    title="ASR + Word Alignment Service",
    description="Speech-to-text service with word-level timing extraction",
    version="1.0.0"
)

def load_model():
    """Load the ASR model once and cache it"""
    global _model_instance
    if _model_instance is None:
        try:
            logger.info(f"Loading ASR model: {ASR_MODEL}")
            _model_instance = WhisperModel(
                ASR_MODEL,
                device="cuda" if os.getenv("CUDA_VISIBLE_DEVICES") else "cpu",
                compute_type=ASR_COMPUTE_TYPE,
                download_root=ASR_MODEL_CACHE
            )
            logger.info("ASR model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load ASR model: {e}")
            raise
    return _model_instance

def process_audio_file(file_path: str, language: Optional[str] = None) -> tuple:
    """Process audio file and return transcription with timing information"""
    try:
        # Load model if not already loaded
        model = load_model()
        
        # Perform transcription with forced alignment if available
        segments, info = model.transcribe(
            file_path,
            language=language,
            task="transcribe",
            beam_size=5,
            best_of=5,
            vad_filter=True,
            word_timestamps=ASR_FORCE_ALIGNMENT
        )
        
        # Convert segments to the expected format
        segments_list = []
        words_list = []
        
        # If we have word timestamps, we can extract them
        if hasattr(info, 'words') and info.words:
            # Process word-level timestamps
            for word in info.words:
                words_list.append(Word(
                    text=word.word,
                    start_ms=int(word.start * 1000),
                    end_ms=int(word.end * 1000),
                    confidence=word.probability if hasattr(word, 'probability') else None
                ))
        
        # Process segments (transcript segments)
        for segment in segments:
            segments_list.append(Segment(
                start_ms=int(segment.start * 1000),
                end_ms=int(segment.end * 1000),
                text=segment.text
            ))
        
        # Get the full text
        full_text = " ".join([seg.text for seg in segments_list])
        
        # Determine if forced alignment was used
        forced_alignment_used = ASR_FORCE_ALIGNMENT and (hasattr(info, 'words') and info.words)
        
        return full_text, segments_list, words_list, forced_alignment_used
        
    except Exception as e:
        logger.error(f"Error processing audio file: {e}")
        raise

@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    # Check if model is loaded
    model_loaded = _model_instance is not None
    return JSONResponse({"status": "ok", "model_loaded": model_loaded})

@app.post("/align")
async def align(request: AlignRequest):
    """Align audio to text with word-level timing"""
    try:
        # Validate request
        if not request.media_path and not request.media_file:
            raise HTTPException(status_code=400, detail="Either media_path or media_file must be provided")
        
        # Handle file input
        temp_file_path = None
        try:
            if request.media_file:
                # Handle uploaded file
                temp_file_path = os.path.join("/tmp", f"asr_upload_{uuid.uuid4()}.tmp")
                with open(temp_file_path, "wb") as buffer:
                    content = await request.media_file.read()
                    buffer.write(content)
                file_path = temp_file_path
            elif request.media_path:
                # Handle file path
                file_path = request.media_path
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=400, detail=f"Media file not found: {file_path}")
                if not os.path.isfile(file_path):
                    raise HTTPException(status_code=400, detail=f"Media path is not a file: {file_path}")
            else:
                raise HTTPException(status_code=400, detail="No media provided")
            
            # Process the audio file
            full_text, segments, words, forced_alignment_used = process_audio_file(
                file_path, 
                request.language
            )
            
            # Check if forced alignment was actually used (if strict mode is enabled)
            degraded = False
            degradation_reason = None
            
            if request.strict and not forced_alignment_used:
                raise HTTPException(
                    status_code=400, 
                    detail="Forced alignment required but not available"
                )
            
            # Build response
            response = AlignResponse(
                text=full_text,
                language=request.language or "en",
                model=request.model_override or ASR_MODEL,
                provider="faster-whisper",
                forced_alignment_used=forced_alignment_used,
                degraded=degraded,
                degradation_reason=degradation_reason,
                segments=segments,
                words=words
            )
            
            return response
            
        finally:
            # Clean up temporary file if it was created
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error in align endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/models")
async def list_models():
    """List available models"""
    # Return the models that are configured
    return JSONResponse({
        "models": [ASR_MODEL, ASR_MODEL_ACCURACY],
        "default": ASR_MODEL,
        "accuracy_override": ASR_MODEL_ACCURACY
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=ASR_PORT)