import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ASR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASR_DIR))

from providers.base import ProviderConfig  # noqa: E402
from providers.faster_whisper_provider import FasterWhisperProvider  # noqa: E402


class _FakeSegment:
    def __init__(self):
        self.start = 0.0
        self.end = 1.0
        self.text = "hello"


class FasterWhisperProviderTests(unittest.TestCase):
    def setUp(self):
        self._previous_cache = os.environ.get("ASR_MODEL_CACHE")

    def tearDown(self):
        if self._previous_cache is None:
            os.environ.pop("ASR_MODEL_CACHE", None)
        else:
            os.environ["ASR_MODEL_CACHE"] = self._previous_cache

    def test_model_load_uses_resolved_asr_model_cache_path(self):
        captured_kwargs = {}

        class _CaptureWhisperModel:
            def __init__(self, *_args, **kwargs):
                captured_kwargs.update(kwargs)

            def transcribe(self, *_args, **_kwargs):
                return ([_FakeSegment()], types.SimpleNamespace(words=[]))

        original_whisper_model = sys.modules["providers.faster_whisper_provider"].WhisperModel
        sys.modules["providers.faster_whisper_provider"].WhisperModel = _CaptureWhisperModel

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                os.environ["ASR_MODEL_CACHE"] = tmp_dir
                provider = FasterWhisperProvider(
                    ProviderConfig(
                        name="faster-whisper",
                        model="whisper-large-v3-turbo",
                        accuracy_model="whisper-large-v3",
                        compute_type="float16",
                        force_alignment=False,
                        diarization_enabled=False,
                        lazy_load_alignment=True,
                    )
                )
                provider.transcribe("/tmp/fake.wav")
        finally:
            sys.modules["providers.faster_whisper_provider"].WhisperModel = original_whisper_model

        self.assertEqual(captured_kwargs.get("download_root"), os.environ.get("ASR_MODEL_CACHE"))

    def test_prefers_resolved_runtime_device_and_compute_type(self):
        captured_kwargs = {}

        class _CaptureWhisperModel:
            def __init__(self, *_args, **kwargs):
                captured_kwargs.update(kwargs)

            def transcribe(self, *_args, **_kwargs):
                return ([_FakeSegment()], types.SimpleNamespace(words=[]))

        original_whisper_model = sys.modules["providers.faster_whisper_provider"].WhisperModel
        sys.modules["providers.faster_whisper_provider"].WhisperModel = _CaptureWhisperModel

        try:
            provider = FasterWhisperProvider(
                ProviderConfig(
                    name="faster-whisper",
                    model="whisper-large-v3-turbo",
                    accuracy_model="whisper-large-v3",
                    compute_type="float16",
                    device="cuda",
                    resolved_device="cpu",
                    resolved_compute_type="float32",
                    force_alignment=False,
                    diarization_enabled=False,
                    lazy_load_alignment=True,
                )
            )
            provider.transcribe("/tmp/fake.wav")
        finally:
            sys.modules["providers.faster_whisper_provider"].WhisperModel = original_whisper_model

        self.assertEqual("cpu", captured_kwargs.get("device"))
        self.assertEqual("float32", captured_kwargs.get("compute_type"))


if __name__ == "__main__":
    unittest.main()
