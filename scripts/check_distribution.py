"""Install a wheel in a fresh environment and exercise it outside the checkout.

Usage: python scripts/check_distribution.py dist/autoschema-0.3.0-py3-none-any.whl
Dependencies are resolved by pip inside the temporary environment. The script
never uploads a distribution or uses the repository's source directory on PYTHONPATH.
"""

import argparse
import os
import subprocess
import tempfile
import venv
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument(
        "--minimum-dependencies", action="store_true", help="Use pandas 1.5.3 and NumPy below 2"
    )
    parser.add_argument(
        "--tests", type=Path, help="Also run a unittest directory against the installed wheel"
    )
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if "autoschema/py.typed" not in names:
            raise RuntimeError("The wheel is missing its PEP 561 type marker.")
        if any(name.startswith(("data/", "results/", "notebooks/", "tests/")) for name in names):
            raise RuntimeError("The wheel unexpectedly includes repository artifacts.")
    with tempfile.TemporaryDirectory(prefix="autoschema-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        binary = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        cli = binary / ("autoschema.exe" if os.name == "nt" else "autoschema")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PIP_CACHE_DIR"] = str(root / "pip-cache")
        env["PYTHONPYCACHEPREFIX"] = str(root / "pycache")
        dependencies = ["pandas==1.5.3", "numpy<2"] if args.minimum_dependencies else []
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel),
                *dependencies,
            ],
            cwd=root,
            env=env,
            check=True,
        )
        smoke = """
import json
import sys
from importlib.metadata import version
from pathlib import Path
import autoschema
import pandas as pd

assert Path(autoschema.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert autoschema.__version__ == version("autoschema")
assert (Path(autoschema.__file__).parent / "py.typed").is_file()
frame = pd.DataFrame({"row_id": range(8), "customer_id": ["C01", "C02"] * 4, "name": ["Amina", "Yusuf"] * 4})
frame.to_csv("sample.csv", index=False)
result = autoschema.convert_csv("sample.csv", out="converted", key_columns=["row_id"])
assert result.summary()["reconstruction_exact"]
assert result.report_path.is_file()
assert len(result.tables) == 2
pd.testing.assert_frame_equal(autoschema.load_result("converted").read_table(), frame)
assert result.query("SELECT COUNT(*) AS n FROM dataset").iloc[0, 0] == 8
print("Installed wheel API, version, types, conversion, persisted result and SQL query: PASS")
"""
        subprocess.run([str(python), "-c", smoke], cwd=root, env=env, check=True)
        subprocess.run([str(cli), "--version"], cwd=root, env=env, check=True)
        subprocess.run(
            [str(cli), "sample.csv", "--out", "cli-result", "--json"],
            cwd=root,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        print("Installed console entry point: PASS")
        if args.tests is not None:
            subprocess.run(
                [str(python), "-m", "unittest", "discover", "-s", str(args.tests.resolve()), "-v"],
                cwd=root,
                env=env,
                check=True,
            )


if __name__ == "__main__":
    main()
