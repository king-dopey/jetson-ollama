import os
import sys
import types
import unittest
import tempfile
from pathlib import Path

ASR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASR_DIR))

from providers.base import ProviderConfig  # noqa: E402
from providers.whisperx_provider import WhisperXProvider  # noqa: E402


class _FakeWhisperModel:
    def transcribe(self, audio, language=None):
        return {
            "language": language or "en",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "hello",
                }
            ]
        }


class WhisperXProviderTests(unittest.TestCase):
    def setUp(self):
        self._original_modules = {name: sys.modules.get(name) for name in ("torchaudio", "whisperx")}

    def tearDown(self):
        for name, module in self._original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def _provider(self) -> WhisperXProvider:
        config = ProviderConfig(
            name="whisperx",
            model="whisper-large-v3-turbo",
            accuracy_model="whisper-large-v3",
            compute_type="float16",
            force_alignment=True,
            diarization_enabled=False,
            lazy_load_alignment=True,
        )
        return WhisperXProvider(config)

    def _provider_with_models(self, model: str, accuracy_model: str) -> WhisperXProvider:
        config = ProviderConfig(
            name="whisperx",
            model=model,
            accuracy_model=accuracy_model,
            compute_type="float16",
            force_alignment=True,
            diarization_enabled=False,
            lazy_load_alignment=True,
        )
        return WhisperXProvider(config)

    def test_transcribe_uses_alignment_api_for_word_timestamps(self):
        whisperx = types.ModuleType("whisperx")
        align_calls = []
        load_align_calls = []
        load_model_calls = []
        fake_model = _FakeWhisperModel()

        def load_model(model_name, *_args, **_kwargs):
            load_model_calls.append(model_name)
            return fake_model

        def load_align_model(language_code, device):
            load_align_calls.append((language_code, device))
            return ("align-model", {"meta": "ok"})

        def align(segments, model_a, metadata, audio, device, return_char_alignments=False):
            align_calls.append((segments, model_a, metadata, audio, device, return_char_alignments))
            return {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "hello",
                        "words": [{"word": "hello", "start": 0.0, "end": 1.0, "confidence": 0.98}],
                    }
                ]
            }

        whisperx.load_model = load_model
        whisperx.load_align_model = load_align_model
        whisperx.align = align
        whisperx.load_audio = lambda file_path: [0.0]
        sys.modules["whisperx"] = whisperx

        provider = self._provider()
        text, segments, words = provider.transcribe("/tmp/fake.wav", language="en", use_alignment=True)

        self.assertEqual("hello", text)
        self.assertEqual(1, len(segments))
        self.assertEqual(1, len(words))
        self.assertEqual(("en", "cpu"), load_align_calls[0])
        self.assertEqual(False, align_calls[0][5])
        self.assertEqual("large-v3", load_model_calls[0])

    def test_accepts_public_alias_for_default_model(self):
        whisperx = types.ModuleType("whisperx")
        load_model_calls = []
        fake_model = _FakeWhisperModel()

        def load_model(model_name, *_args, **_kwargs):
            load_model_calls.append(model_name)
            return fake_model

        whisperx.load_model = load_model
        whisperx.load_audio = lambda _file_path: [0.0]
        whisperx.load_align_model = lambda **_kwargs: ("align-model", {"meta": "ok"})
        whisperx.align = lambda *args, **kwargs: {"segments": args[0]}
        sys.modules["whisperx"] = whisperx

        provider = self._provider_with_models("whisper-large-v3-turbo", "whisper-large-v3")
        provider.transcribe("/tmp/fake.wav", language="en", use_alignment=False)
        self.assertEqual("large-v3-turbo", load_model_calls[0])

    def test_accepts_provider_model_name_unchanged(self):
        whisperx = types.ModuleType("whisperx")
        load_model_calls = []
        fake_model = _FakeWhisperModel()

        def load_model(model_name, *_args, **_kwargs):
            load_model_calls.append(model_name)
            return fake_model

        whisperx.load_model = load_model
        whisperx.load_audio = lambda _file_path: [0.0]
        whisperx.load_align_model = lambda **_kwargs: ("align-model", {"meta": "ok"})
        whisperx.align = lambda *args, **kwargs: {"segments": args[0]}
        sys.modules["whisperx"] = whisperx

        provider = self._provider_with_models("large-v3-turbo", "large-v3")
        provider.transcribe("/tmp/fake.wav", language="en", use_alignment=False)
        self.assertEqual("large-v3-turbo", load_model_calls[0])

    def test_invalid_model_name_surfaces_actionable_error(self):
        whisperx = types.ModuleType("whisperx")
        whisperx.load_audio = lambda _file_path: [0.0]
        whisperx.load_model = lambda *_args, **_kwargs: _FakeWhisperModel()
        whisperx.load_align_model = lambda **_kwargs: ("align-model", {"meta": "ok"})
        whisperx.align = lambda *args, **kwargs: {"segments": args[0]}
        sys.modules["whisperx"] = whisperx

        provider = self._provider_with_models("whisper-not-a-real-model", "whisper-large-v3")

        with self.assertRaises(Exception) as ctx:
            provider.transcribe("/tmp/fake.wav", language="en", use_alignment=False)

        message = str(ctx.exception)
        self.assertIn("received='whisper-not-a-real-model'", message)
        self.assertIn("normalized='whisper-not-a-real-model'", message)
        self.assertIn("supported provider models=", message)

    def test_transcribe_shims_missing_torchaudio_backend_apis(self):
        torchaudio = types.ModuleType("torchaudio")
        torchaudio.__version__ = "2.11.0"
        sys.modules["torchaudio"] = torchaudio

        whisperx = types.ModuleType("whisperx")
        load_model_calls = []
        fake_model = _FakeWhisperModel()

        def load_model(model_name, *_args, **_kwargs):
            import torchaudio as ta
            ta.set_audio_backend("soundfile")
            load_model_calls.append(model_name)
            return fake_model

        whisperx.load_model = load_model
        whisperx.load_audio = lambda _file_path: [0.0]
        whisperx.load_align_model = lambda language_code, device: ("align-model", {"meta": "ok"})
        whisperx.align = lambda segments, *_args, **_kwargs: {"segments": segments}
        sys.modules["whisperx"] = whisperx

        provider = self._provider()
        text, segments, words = provider.transcribe("/tmp/fake.wav", language="en", use_alignment=True)

        self.assertEqual("hello", text)
        self.assertEqual(1, len(segments))
        self.assertEqual(0, len(words))
        self.assertEqual("large-v3", load_model_calls[0])
        self.assertTrue(hasattr(torchaudio, "set_audio_backend"))
        self.assertTrue(hasattr(torchaudio, "get_audio_backend"))

    def test_model_load_uses_resolved_asr_model_cache_path(self):
        whisperx = types.ModuleType("whisperx")
        captured_download_roots = []
        fake_model = _FakeWhisperModel()

        def load_model(_model_name, *_args, **kwargs):
            captured_download_roots.append(kwargs.get("download_root"))
            return fake_model

        whisperx.load_model = load_model
        whisperx.load_audio = lambda _file_path: [0.0]
        whisperx.load_align_model = lambda **_kwargs: ("align-model", {"meta": "ok"})
        whisperx.align = lambda *args, **kwargs: {"segments": args[0]}
        sys.modules["whisperx"] = whisperx

        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = os.environ.get("ASR_MODEL_CACHE")
            os.environ["ASR_MODEL_CACHE"] = tmp_dir
            try:
                provider = self._provider()
                provider.transcribe("/tmp/fake.wav", language="en", use_alignment=False)
            finally:
                if previous is None:
                    os.environ.pop("ASR_MODEL_CACHE", None)
                else:
                    os.environ["ASR_MODEL_CACHE"] = previous

        self.assertEqual(tmp_dir, captured_download_roots[0])

    def test_prefers_resolved_runtime_device_and_compute_type(self):
        whisperx = types.ModuleType("whisperx")
        load_model_kwargs = []
        fake_model = _FakeWhisperModel()

        def load_model(_model_name, *_args, **kwargs):
            load_model_kwargs.append(kwargs)
            return fake_model

        whisperx.load_model = load_model
        whisperx.load_audio = lambda _file_path: [0.0]
        whisperx.load_align_model = lambda **_kwargs: ("align-model", {"meta": "ok"})
        whisperx.align = lambda *args, **kwargs: {"segments": args[0]}
        sys.modules["whisperx"] = whisperx

        config = ProviderConfig(
            name="whisperx",
            model="whisper-large-v3-turbo",
            accuracy_model="whisper-large-v3",
            compute_type="float16",
            device="cuda",
            resolved_device="cpu",
            resolved_compute_type="float32",
            force_alignment=True,
            diarization_enabled=False,
            lazy_load_alignment=True,
        )
        provider = WhisperXProvider(config)
        provider.transcribe("/tmp/fake.wav", language="en", use_alignment=False)

        self.assertEqual("cpu", load_model_kwargs[0]["device"])
        self.assertEqual("float32", load_model_kwargs[0]["compute_type"])


if __name__ == "__main__":
    unittest.main()
