import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ASR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASR_DIR))

from cache_config import (  # noqa: E402
    initialize_cache_environment,
    resolve_cache_paths,
    validate_writable_directory,
)


class CacheConfigTests(unittest.TestCase):
    def test_resolve_cache_paths_defaults(self):
        paths = resolve_cache_paths(env={}, cwd="/app")

        self.assertEqual("/app/models", paths.model_cache)
        self.assertEqual("/app/models/hf", paths.hf_home)
        self.assertEqual("/app/models/hf/hub", paths.huggingface_hub_cache)
        self.assertEqual("/app/models/hf/transformers", paths.transformers_cache)
        self.assertEqual("/app/models/xdg", paths.xdg_cache_home)

    def test_resolve_cache_paths_uses_explicit_env_overrides(self):
        env = {
            "ASR_MODEL_CACHE": "/data/asr-cache",
            "HF_HOME": "/data/custom-hf",
            "TRANSFORMERS_CACHE": "/data/custom-transformers",
        }

        paths = resolve_cache_paths(env=env, cwd="/app")

        self.assertEqual("/data/asr-cache", paths.model_cache)
        self.assertEqual("/data/custom-hf", paths.hf_home)
        self.assertEqual("/data/custom-hf/hub", paths.huggingface_hub_cache)
        self.assertEqual("/data/custom-transformers", paths.transformers_cache)
        self.assertEqual("/data/asr-cache/xdg", paths.xdg_cache_home)

    def test_initialize_cache_environment_sets_expected_env_vars(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.dict(
                os.environ,
                {
                    "ASR_MODEL_CACHE": tmp_dir,
                },
                clear=True,
            ):
                paths = initialize_cache_environment()

                self.assertEqual(tmp_dir, paths.model_cache)
                self.assertEqual(tmp_dir, os.environ["ASR_MODEL_CACHE"])
                self.assertEqual(f"{tmp_dir}/hf", os.environ["HF_HOME"])
                self.assertEqual(f"{tmp_dir}/hf/hub", os.environ["HUGGINGFACE_HUB_CACHE"])
                self.assertEqual(f"{tmp_dir}/hf/transformers", os.environ["TRANSFORMERS_CACHE"])
                self.assertEqual(f"{tmp_dir}/xdg", os.environ["XDG_CACHE_HOME"])

    def test_validate_writable_directory_surfaces_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch(
                "cache_config.tempfile.NamedTemporaryFile",
                side_effect=PermissionError(13, "Permission denied", tmp_dir),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    validate_writable_directory(tmp_dir, "asr_model_cache")

        message = str(ctx.exception)
        self.assertIn("asr_model_cache_not_writable", message)
        self.assertIn("label=asr_model_cache", message)
        self.assertIn("Permission denied", message)


if __name__ == "__main__":
    unittest.main()
