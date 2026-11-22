"""Exercise the same checked-in fixture manifest used by the native R package."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/shared_validation.py"
_SPEC = importlib.util.spec_from_file_location("shared_dataset_contract", _SCRIPT)
contract = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(contract)


class SharedDatasetTests(unittest.TestCase):
    def test_manifest_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            for case in contract.cases():
                with self.subTest(case=case["id"]):
                    contract.check_python_case(case, Path(temporary))


if __name__ == "__main__":
    unittest.main()
