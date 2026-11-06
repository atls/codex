"""Build Python-owned suite configuration and invoke the official Promptfoo CLI."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE))
from configuration import build_suite, suite_cases
from runtime.session import evaluation_session


def absolute_references(value):
    if isinstance(value, list):
        return [absolute_references(entry) for entry in value]
    if isinstance(value, dict):
        return {key: absolute_references(entry) for key, entry in value.items()}
    if isinstance(value, str) and value.startswith("file://"):
        target = value[7:]
        return (
            "file://" + str(SUITE / target)
            if not Path(target.split(":", 1)[0]).is_absolute()
            else value
        )
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "suite",
        choices=[
            "native",
            "controller",
            "ordinary",
            "calibration",
            "regrade",
            "tasks",
            "corpus",
        ],
    )
    parser.add_argument("--validate", action="store_true")
    args, extra = parser.parse_known_args()
    os.environ["PROMPTFOO_PYTHON"] = sys.executable
    if extra[:1] == ["--"]:
        extra = extra[1:]
    with evaluation_session(
        suite_cases(args.suite), install_skill=args.suite not in {"tasks", "corpus"}
    ) as runtime:
        config = absolute_references(build_suite(args.suite, runtime))
        with tempfile.TemporaryDirectory(
            prefix="model-fit-promptfoo-config-"
        ) as directory:
            path = Path(directory) / "suite.json"
            path.write_text(json.dumps(config, ensure_ascii=False))
            command = ["yarn", "exec", "promptfoo"]
            validate = subprocess.run(
                [*command, "validate", "config", "--config", str(path)], cwd=SUITE
            )
            if args.validate or validate.returncode:
                return validate.returncode
            return subprocess.run(
                [
                    *command,
                    "eval",
                    "--config",
                    str(path),
                    "--no-cache",
                    "--max-concurrency",
                    "1",
                    *extra,
                ],
                cwd=SUITE,
            ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
