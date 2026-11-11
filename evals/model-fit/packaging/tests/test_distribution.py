import json
import os
import shutil
import subprocess
import sys
import tempfile
import pytest
import zipfile
from pathlib import Path

from fixtures.distribution import ROOT, WORKFLOW, archive, copy_source


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    copy_source(ROOT, root)
    shutil.copytree(ROOT / ".github/packaging", root / ".github/packaging")
    (root / WORKFLOW.parent).mkdir(parents=True)
    shutil.copyfile(ROOT / WORKFLOW, root / WORKFLOW)
    return root


@pytest.fixture
def archives(source):
    return {
        name: archive(source, name)
        for name in ("vector-prime", "vector-prime-guidance")
    }


def test_variants_share_assessor_and_exclude_development_files(source, archives):
    assert not ((source / "evals").exists())
    contents = {}
    for name, archive_path in archives.items():
        with zipfile.ZipFile(archive_path) as package:
            contents[name] = {
                member[len(name) + 1 :]: package.read(member)
                for member in package.namelist()
                if not member.endswith("/")
            }
    full, cli = contents["vector-prime"], contents["vector-prime-guidance"]
    for name, content in cli.items():
        if name.startswith("src/") or name == "skills/model-fit/SKILL.md":
            assert content == full[name], name
    assert "hooks/hooks.json" in full
    assert "hooks/hooks.json" not in cli
    assert "src/vector_prime/application/assessment/lifecycle.py" in cli
    assert not (
        any(
            (
                name.startswith(
                    (
                        "src/vector_prime/application/switch/",
                        "src/vector_prime/application/handoff/",
                        "src/vector_prime/entrypoints/hooks/",
                    )
                )
                for name in cli
            )
        )
    )
    for files in (full, cli):
        assert not (
            any(("tests/" in name or name.startswith("evals/") for name in files))
        )
    metadata = json.loads(cli["plugin.json"])
    assert metadata["extensions"]["com.openai"]["requires_local_executor"]
    assert "hooks" not in metadata
    assert "hooks" not in metadata["extensions"]["com.openai"]


def test_unlisted_files_and_selected_symlinks_stay_out(source):
    (source / "private-fixture.json").write_text('{"fixture":true}')
    (source / "src/vector_prime/linked.py").symlink_to(source / "private-fixture.json")
    with zipfile.ZipFile(archive(source, "vector-prime")) as package:
        assert "vector-prime/private-fixture.json" not in package.namelist()
        assert "vector-prime/src/vector_prime/linked.py" not in package.namelist()


@pytest.mark.parametrize("name", ["vector-prime", "vector-prime-guidance"])
def test_clean_cli_install_without_hooks_or_submission_state(archives, name):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        archive_path = archives[name]
        with zipfile.ZipFile(archive_path) as zipped:
            zipped.extractall(root / "installed")
        package = root / "installed" / name
        home = root / "codex-home"
        home.mkdir()
        (home / "config.toml").write_text("[features]\nhooks=false\nplugins=false\n")
        env = {**os.environ, "CODEX_HOME": str(home)}
        env.pop("PYTHONPATH", None)
        profile = {"model": "gpt-6-luna", "effort": "low", "speed": None}
        request = {
            "task": "Keep my selected profile",
            "active_profile": profile,
            "prior_choice": {
                "user_selected": True,
                "same_work": True,
                "profile": profile,
            },
        }
        command = [
            "uv",
            "run",
            "--locked",
            "--project",
            str(package),
            "--python",
            sys.executable,
            "vp",
        ]
        result = subprocess.run(
            command,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            env=env,
            cwd=root,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["decision"] == "keep"
        assert not ((home / ".tmp").exists())
        malformed = subprocess.run(
            command,
            input="{}",
            text=True,
            capture_output=True,
            env=env,
            cwd=root,
            timeout=30,
        )
        assert malformed.returncode == 2
        assert malformed.stdout == ""


@pytest.mark.parametrize("name", ["vector-prime", "vector-prime-guidance"])
def test_noneditable_evaluator_uses_installed_skill_after_source_removal(
    archives, name
):
    archive_path = archives[name]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with zipfile.ZipFile(archive_path) as zipped:
            zipped.extractall(root)
        package = root / name
        home = root / "home"
        home.mkdir()
        (home / "auth.json").write_text('{"fixture":true}')
        command = [
            "uv",
            "run",
            "--locked",
            "--no-editable",
            "--project",
            str(package),
            "--python",
            sys.executable,
            "python",
            "-c",
            """
import sys
from pathlib import Path
from unittest.mock import patch
from vector_prime.infrastructure.adapters.codex.transport.assessment import session

source = Path(sys.argv[1])
expected = (source / "skills/model-fit/references/assessment-policy.md").read_bytes()
(source / "skills").rename(source / "removed-skills")
(source / "src").rename(source / "removed-src")
with patch.object(session.subprocess, "Popen"), patch.object(session.AppServer, "call", return_value={}), patch.object(session.AppServer, "send"):
    with session.AppServer(source) as app:
        assert app.skill_file.is_file()
        assert (app.skill_file.parent / "references/assessment-policy.md").read_bytes() == expected
print("installed evaluator skill available without source")
""",
            str(package),
        ]
        result = subprocess.run(
            command,
            cwd=root,
            env={**os.environ, "CODEX_HOME": str(home)},
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "installed evaluator skill available without source" in result.stdout
