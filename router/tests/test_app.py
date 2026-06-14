import os
from pathlib import Path
import sys
import types
import unittest
import logging

logging.getLogger("router").setLevel(logging.WARNING)

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
        coder = MODEL_POLICY["qwen3-coder:30b"]
        self.assertEqual(coder["keep_alive"], -1)
        self.assertEqual(coder["think"], False)
        self.assertEqual(coder["options"]["num_ctx"], 65536)
        self.assertTrue(coder["warmup"])

        thinker = MODEL_POLICY["qwen3.6:35b-a3b"]
        self.assertEqual(thinker["keep_alive"], 0)
        self.assertEqual(thinker["think"], True)
        self.assertEqual(thinker["options"]["num_ctx"], 32768)
        self.assertEqual(thinker["warmup"], False)

        verifier = MODEL_POLICY["nemotron-cascade-2:30b"]
        self.assertEqual(verifier["keep_alive"], "10m")
        self.assertEqual(verifier["think"], True)
        self.assertEqual(verifier["options"]["num_ctx"], 16384)
        self.assertEqual(verifier["warmup"], False)

        # Test new model
        next_model = MODEL_POLICY["qwen3-coder-next:q4_K_M"]
        self.assertEqual(next_model["keep_alive"], 0)
        self.assertEqual(next_model["think"], False)
        self.assertEqual(next_model["options"]["num_ctx"], 16384)
        self.assertEqual(next_model["warmup"], False)

    def test_build_payload_forwards_unlocked_options_format_and_keep_alive(self):
        body = {
            "model": "qwen3-coder:30b",
            "messages": [{"role": "user", "content": "hi"}],
            "keep_alive": "5m",
            "format": "json",
            "options": {
                "num_batch": 1024,          # not policy-locked: client should win
                "repeat_penalty": 1.2,       # not policy-locked: client should win
            },
            "temperature": 0.4,
            "max_tokens": 256,
        }
        payload = _build_ollama_payload(body, think=False)

        self.assertEqual(payload["keep_alive"], "5m")
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["num_batch"], 1024)
        self.assertEqual(payload["options"]["repeat_penalty"], 1.2)
        self.assertEqual(payload["options"]["temperature"], 0.4)
        self.assertEqual(payload["options"]["num_predict"], 256)
        # Policy default still present because client did not override it.
        self.assertEqual(payload["options"]["num_ctx"], 65536)


    def test_build_payload_policy_num_ctx_overrides_client(self):
        body = {
            "model": "qwen3-coder:30b",
            "messages": [{"role": "user", "content": "hi"}],
            "options": {"num_ctx": 16384},
        }
        with self.assertLogs("router", level="INFO") as cm:
            payload = _build_ollama_payload(body, think=False)
        self.assertEqual(payload["options"]["num_ctx"], 65536)
        self.assertTrue(any("overriding client num_ctx" in m for m in cm.output))


    def test_build_payload_uses_policy_defaults_when_client_silent(self):
        body = {
            "model": "qwen3-coder:30b",
            "messages": [{"role": "user", "content": "hi"}],
        }
        payload = _build_ollama_payload(body, think=False)
        opts = payload["options"]
        self.assertEqual(opts["num_ctx"], 65536)
        self.assertEqual(opts["num_batch"], 512)
        self.assertEqual(opts["temperature"], 0.1)
        self.assertEqual(payload["keep_alive"], -1)  # from policy


    def test_build_payload_uses_model_keep_alive_when_request_omits_it(self):
        body = {
            "model": "nemotron-cascade-2:30b",
            "messages": [{"role": "user", "content": "Verify this answer."}],
        }

        payload = _build_ollama_payload(body, think=True)

        self.assertEqual(payload["keep_alive"], "10m")


if __name__ == "__main__":
    unittest.main()