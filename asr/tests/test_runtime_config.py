import unittest
from unittest import mock
from pathlib import Path
import sys

ASR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASR_DIR))

import runtime_config  # noqa: E402


class RuntimeConfigTests(unittest.TestCase):
    def test_resolves_cuda_float16_when_cuda_is_available(self):
        with mock.patch.object(
            runtime_config,
            "_detect_torch_backend",
            return_value=runtime_config.TorchBackendInfo(
                import_ok=True,
                version="2.8.0",
                cuda_available=True,
                cuda_version="12.6",
                device_count=1,
            ),
        ), mock.patch.object(
            runtime_config,
            "_detect_ctranslate2_backend",
            return_value=runtime_config.CTranslate2Info(
                import_ok=True,
                version="4.8.0",
                cuda_supported=True,
            ),
        ):
            resolved = runtime_config.resolve_runtime(
                {
                    "ASR_DEVICE": "auto",
                    "ASR_EXPECT_DEVICE": "cuda",
                    "ASR_COMPUTE_TYPE": "float16",
                }
            )

        self.assertEqual("cuda", resolved.resolved_device)
        self.assertEqual("float16", resolved.resolved_compute_type)
        self.assertFalse(resolved.degraded)

    def test_float16_on_cpu_fails_fast_without_fallback(self):
        with mock.patch.object(
            runtime_config,
            "_detect_torch_backend",
            return_value=runtime_config.TorchBackendInfo(
                import_ok=True,
                version="2.8.0+cpu",
                cuda_available=False,
                cuda_version=None,
                device_count=0,
            ),
        ), mock.patch.object(
            runtime_config,
            "_detect_ctranslate2_backend",
            return_value=runtime_config.CTranslate2Info(
                import_ok=True,
                version="4.8.0",
                cuda_supported=False,
            ),
        ):
            with self.assertRaises(runtime_config.RuntimeResolutionError) as ctx:
                runtime_config.resolve_runtime(
                    {
                        "ASR_DEVICE": "auto",
                        "ASR_EXPECT_DEVICE": "auto",
                        "ASR_COMPUTE_TYPE": "float16",
                        "ASR_ALLOW_COMPUTE_FALLBACK": "0",
                    }
                )

        self.assertEqual("asr_compute_type_unsupported_for_backend", ctx.exception.code)

    def test_float16_on_cpu_degrades_with_explicit_fallback(self):
        with mock.patch.object(
            runtime_config,
            "_detect_torch_backend",
            return_value=runtime_config.TorchBackendInfo(
                import_ok=True,
                version="2.8.0+cpu",
                cuda_available=False,
                cuda_version=None,
                device_count=0,
            ),
        ), mock.patch.object(
            runtime_config,
            "_detect_ctranslate2_backend",
            return_value=runtime_config.CTranslate2Info(
                import_ok=True,
                version="4.8.0",
                cuda_supported=False,
            ),
        ):
            resolved = runtime_config.resolve_runtime(
                {
                    "ASR_DEVICE": "auto",
                    "ASR_EXPECT_DEVICE": "auto",
                    "ASR_COMPUTE_TYPE": "float16",
                    "ASR_ALLOW_COMPUTE_FALLBACK": "1",
                    "ASR_ALLOW_DEGRADED_BACKEND": "1",
                }
            )

        self.assertEqual("cpu", resolved.resolved_device)
        self.assertEqual("float32", resolved.resolved_compute_type)
        self.assertTrue(resolved.degraded)
        self.assertEqual("asr_compute_type_unsupported_for_backend", resolved.degradation_reason)

    def test_expected_cuda_fails_fast_when_cuda_is_unavailable(self):
        with mock.patch.object(
            runtime_config,
            "_detect_torch_backend",
            return_value=runtime_config.TorchBackendInfo(
                import_ok=True,
                version="2.8.0+cpu",
                cuda_available=False,
                cuda_version=None,
                device_count=0,
            ),
        ), mock.patch.object(
            runtime_config,
            "_detect_ctranslate2_backend",
            return_value=runtime_config.CTranslate2Info(
                import_ok=True,
                version="4.8.0",
                cuda_supported=False,
            ),
        ):
            with self.assertRaises(runtime_config.RuntimeResolutionError) as ctx:
                runtime_config.resolve_runtime(
                    {
                        "ASR_DEVICE": "auto",
                        "ASR_EXPECT_DEVICE": "cuda",
                        "ASR_COMPUTE_TYPE": "float16",
                        "ASR_ALLOW_DEGRADED_BACKEND": "0",
                    }
                )

        self.assertEqual("asr_cuda_unavailable_on_orin_deployment", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
