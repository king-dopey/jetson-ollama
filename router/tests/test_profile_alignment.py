from pathlib import Path
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
ROUTER_POLICY = ROOT / "router" / "model_policy.yml"
ORIN_PROFILE = ROOT / "profiles" / "orin" / "models.yaml"
THOR_PROFILE = ROOT / "profiles" / "thor" / "models.yaml"


def _load_models(path: Path) -> dict[str, int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result: dict[str, int] = {}
    for item in data.get("models", []) or []:
        model = item.get("model")
        options = item.get("options") or {}
        if model and "num_ctx" in options:
            result[str(model)] = int(options["num_ctx"])
    return result


class ProfileAlignmentTests(unittest.TestCase):
    def test_shared_model_num_ctx_matches_router_policy(self):
        router = _load_models(ROUTER_POLICY)
        orin = _load_models(ORIN_PROFILE)
        thor = _load_models(THOR_PROFILE)

        shared = set(router) & set(orin) & set(thor)
        self.assertTrue(shared)

        for model in sorted(shared):
            self.assertEqual(orin[model], router[model], f"Orin mismatch for {model}")
            self.assertEqual(thor[model], router[model], f"Thor mismatch for {model}")


if __name__ == "__main__":
    unittest.main()
