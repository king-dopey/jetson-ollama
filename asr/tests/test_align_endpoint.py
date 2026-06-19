import asyncio
import os
import tempfile
from pathlib import Path
import sys
import types
import unittest

ASR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASR_DIR))


def _install_dependency_stubs() -> None:
    if "fastapi" not in sys.modules:
        fastapi = types.ModuleType("fastapi")

        class FastAPI:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def get(self, *args, **kwargs):
                def decorator(func):
                    return func

                return decorator

            def post(self, *args, **kwargs):
                def decorator(func):
                    return func

                return decorator

        class HTTPException(Exception):
            def __init__(self, status_code: int, detail: str):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        class Request:
            pass

        class UploadFile:
            pass

        fastapi.FastAPI = FastAPI
        fastapi.HTTPException = HTTPException
        fastapi.Request = Request
        fastapi.UploadFile = UploadFile
        sys.modules["fastapi"] = fastapi

    if "fastapi.responses" not in sys.modules:
        responses = types.ModuleType("fastapi.responses")

        class JSONResponse:
            def __init__(self, content, status_code: int = 200):
                self.content = content
                self.status_code = status_code

        responses.JSONResponse = JSONResponse
        sys.modules["fastapi.responses"] = responses

    if "pydantic" not in sys.modules:
        pydantic = types.ModuleType("pydantic")

        class BaseModel:
            def __init__(self, **kwargs):
                fields = getattr(self.__class__, "__annotations__", {})
                for key in fields:
                    if key in kwargs:
                        value = kwargs[key]
                    else:
                        value = getattr(self.__class__, key, None)
                    setattr(self, key, value)
                for key, value in kwargs.items():
                    if key not in fields:
                        setattr(self, key, value)

        pydantic.BaseModel = BaseModel
        sys.modules["pydantic"] = pydantic

    if "faster_whisper" not in sys.modules:
        faster_whisper = types.ModuleType("faster_whisper")

        class WhisperModel:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        faster_whisper.WhisperModel = WhisperModel
        sys.modules["faster_whisper"] = faster_whisper


_install_dependency_stubs()
os.environ.setdefault("ASR_MODEL_CACHE", os.path.join(tempfile.gettempdir(), "model64-asr-test-cache"))

import app as app_module  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class _FakeJSONRequest:
    def __init__(self, payload):
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    async def json(self):
        return self._payload


class AlignEndpointSmokeTests(unittest.TestCase):
    def setUp(self):
        self._original_process_audio_file = app_module.process_audio_file
        self._original_providers = dict(app_module._providers)
        self._original_whisperx = sys.modules.get("whisperx")

    def tearDown(self):
        app_module.process_audio_file = self._original_process_audio_file
        app_module._providers = self._original_providers
        if self._original_whisperx is None:
            sys.modules.pop("whisperx", None)
        else:
            sys.modules["whisperx"] = self._original_whisperx

    def test_align_json_smoke_with_mocked_processing(self):
        app_module.process_audio_file = lambda *args, **kwargs: (
            "hello world",
            [{"start_ms": 0, "end_ms": 900, "text": "hello world"}],
            [{"text": "hello", "start_ms": 0, "end_ms": 400, "confidence": 0.99}],
            True,
        )

        req = _FakeJSONRequest(
            {
                "audio_path": __file__,
                "return_word_timestamps": True,
                "prefer_forced_alignment": True,
                "language": "en",
            }
        )
        response = asyncio.run(app_module.align(req))

        self.assertEqual("hello world", response.text)
        self.assertEqual("whisperx", response.provider)
        self.assertTrue(response.forced_alignment_used)
        self.assertEqual(1, len(response.words))

    def test_align_surfaces_provider_stage_diagnostics(self):
        app_module.process_audio_file = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("provider 'whisperx' processing failed: WhisperX stage 'dependency_import' failed")
        )

        req = _FakeJSONRequest({"audio_path": __file__, "prefer_forced_alignment": True})

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(app_module.align(req))

        self.assertEqual(500, ctx.exception.status_code)
        self.assertIn("stage 'dependency_import'", str(ctx.exception.detail))

    def test_align_uses_public_default_alias_without_model_load_failure(self):
        app_module.process_audio_file = self._original_process_audio_file
        app_module._providers = {}

        whisperx = types.ModuleType("whisperx")

        class _FakeModel:
            def transcribe(self, audio, language=None):
                return {
                    "language": language or "en",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
                }

        def _load_model(model_name, *_args, **_kwargs):
            if model_name not in {"large-v3", "large-v3-turbo"}:
                raise RuntimeError(
                    f"Invalid model size '{model_name}', expected one of: large-v3-turbo, large-v3, turbo"
                )
            return _FakeModel()

        whisperx.load_model = _load_model
        whisperx.load_audio = lambda _file_path: [0.0]
        whisperx.load_align_model = lambda language_code, device: ("align-model", {"meta": "ok"})
        whisperx.align = lambda segments, *_args, **_kwargs: {
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "hello",
                    "words": [{"word": "hello", "start": 0.0, "end": 1.0, "confidence": 0.95}],
                }
                for _ in segments
            ]
        }
        sys.modules["whisperx"] = whisperx

        req = _FakeJSONRequest({"audio_path": __file__, "return_word_timestamps": True, "prefer_forced_alignment": True})
        response = asyncio.run(app_module.align(req))

        self.assertEqual("hello", response.text)
        self.assertTrue(response.forced_alignment_used)
        self.assertEqual("whisper-large-v3-turbo", response.model)


if __name__ == "__main__":
    unittest.main()
