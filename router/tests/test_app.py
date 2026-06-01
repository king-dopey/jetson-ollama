import os
from pathlib import Path
import sys
import types
import unittest

ROUTER_DIR = Path(__file__).resolve().parents[1]
os.environ["MODEL_POLICY_FILE"] = str(ROUTER_DIR / "model_policy.yml")
sys.path.insert(0, str(ROUTER_DIR))


def _install_dependency_stubs() -> None:
    if "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")

        class Timeout:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class AsyncClient:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        httpx.Timeout = Timeout
        httpx.AsyncClient = AsyncClient
        sys.modules["httpx"] = httpx

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

        fastapi.FastAPI = FastAPI
        fastapi.HTTPException = HTTPException
        fastapi.Request = Request
        sys.modules["fastapi"] = fastapi

    if "fastapi.responses" not in sys.modules:
        responses = types.ModuleType("fastapi.responses")

        class JSONResponse:
            def __init__(self, content, status_code: int = 200):
                self.content = content
                self.status_code = status_code

        class StreamingResponse:
            def __init__(self, content, media_type: str | None = None):
                self.content = content
                self.media_type = media_type

        responses.JSONResponse = JSONResponse
        responses.StreamingResponse = StreamingResponse
        sys.modules["fastapi.responses"] = responses


_install_dependency_stubs()

from app import MODEL_POLICY, _build_ollama_payload  # noqa: E402


class RouterPayloadTests(unittest.TestCase):
    def test_model_policy_includes_all_served_models(self):
        self.assertEqual(MODEL_POLICY["qwen3-coder:30b"], {"keep_alive": -1, "think": False})
        self.assertEqual(MODEL_POLICY["qwen3.6:35b-a3b"], {"keep_alive": -1, "think": True})
        self.assertEqual(MODEL_POLICY["nemotron-cascade-2:30b"], {"keep_alive": "10m", "think": True})
        self.assertEqual(MODEL_POLICY["qwen2.5-coder:32b-instruct"], {"keep_alive": 0, "think": True})

    def test_build_payload_forwards_options_format_and_keep_alive(self):
        schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "cue_selection",
                "schema": {
                    "type": "object",
                    "properties": {"cue_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["cue_ids"],
                },
            },
        }
        body = {
            "model": "qwen3-coder:30b",
            "messages": [{"role": "user", "content": "Return strict JSON."}],
            "keep_alive": "25m",
            "temperature": 0.2,
            "max_tokens": 32,
            "options": {
                "num_ctx": 65536,
                "num_predict": 400,
                "cache_type_k": "q8_0",
                "cache_type_v": "q8_0",
                "num_keep": 128,
            },
            "format": schema,
        }

        payload = _build_ollama_payload(body, think=False)

        self.assertEqual(payload["keep_alive"], "25m")
        self.assertEqual(payload["think"], False)
        self.assertEqual(payload["format"], schema)
        self.assertEqual(payload["options"]["num_ctx"], 65536)
        self.assertEqual(payload["options"]["num_predict"], 400)
        self.assertEqual(payload["options"]["cache_type_k"], "q8_0")
        self.assertEqual(payload["options"]["cache_type_v"], "q8_0")
        self.assertEqual(payload["options"]["num_keep"], 128)
        self.assertEqual(payload["options"]["temperature"], 0.2)

    def test_build_payload_uses_model_keep_alive_when_request_omits_it(self):
        body = {
            "model": "nemotron-cascade-2:30b",
            "messages": [{"role": "user", "content": "Verify this answer."}],
        }

        payload = _build_ollama_payload(body, think=True)

        self.assertEqual(payload["keep_alive"], "10m")


if __name__ == "__main__":
    unittest.main()