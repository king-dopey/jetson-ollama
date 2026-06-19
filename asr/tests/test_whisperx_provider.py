import sys
import types
import unittest
from pathlib import Path

ASR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASR_DIR))

from providers.base import ProviderConfig  # noqa: E402
from providers.whisperx_provider import WhisperXProvider  # noqa: E402


class _FakeWhisperModel:
    def transcribe(self, audio, language=None):
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


class WhisperXProviderCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self._original_modules = {
            name: sys.modules.get(name)
            for name in ("torchaudio", "whisperx")
        }

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

    def test_transcribe_shims_missing_torchaudio_backend_apis(self):
        torchaudio = types.ModuleType("torchaudio")
        torchaudio.__version__ = "2.11.0"
        sys.modules["torchaudio"] = torchaudio

        whisperx = types.ModuleType("whisperx")

        def load_model(*args, **kwargs):
            import torchaudio as ta
            ta.set_audio_backend("soundfile")
            return _FakeWhisperModel()

        whisperx.load_model = load_model
        whisperx.load_audio = lambda file_path: [0.0]
        sys.modules["whisperx"] = whisperx

        provider = self._provider()
        text, segments, words = provider.transcribe("/tmp/fake.wav", language="en", use_alignment=True)

        self.assertEqual("hello", text)
        self.assertEqual(1, len(segments))
        self.assertEqual(1, len(words))
        self.assertTrue(hasattr(torchaudio, "set_audio_backend"))
        self.assertTrue(hasattr(torchaudio, "get_audio_backend"))

    def test_transcribe_reports_actionable_stage_on_audio_load_failure(self):
        torchaudio = types.ModuleType("torchaudio")
        torchaudio.set_audio_backend = lambda *_args, **_kwargs: None
        torchaudio.get_audio_backend = lambda: "soundfile"
        sys.modules["torchaudio"] = torchaudio

        whisperx = types.ModuleType("whisperx")
        whisperx.load_model = lambda *args, **kwargs: _FakeWhisperModel()

        def _raise_load_audio(_file_path):
            raise ValueError("decode failed")

        whisperx.load_audio = _raise_load_audio
        sys.modules["whisperx"] = whisperx

        provider = self._provider()

        with self.assertRaises(RuntimeError) as ctx:
            provider.transcribe("/tmp/fake.wav", language="en", use_alignment=True)

        self.assertIn("stage 'audio_load'", str(ctx.exception))
        self.assertIn("decode failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
