import pytest

import testrun


@pytest.mark.parametrize("manifest,expected", [
    ("pom.xml", ["mvn", "-q", "test"]),
    ("build.gradle.kts", ["gradle", "test"]),
    ("Cargo.toml", ["cargo", "test"]),
    ("package.json", ["npm", "test"]),
])
def test_command_selection(tmp_path, manifest, expected):
    (tmp_path / manifest).write_text("x", encoding="utf-8")
    assert testrun.test_command(tmp_path) == expected


def test_python_uses_uv_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert testrun.test_command(tmp_path) == ["uv", "run", "pytest"]


def test_flutter_vs_dart(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: x\nflutter:\n  sdk: flutter\n", encoding="utf-8")
    assert testrun.test_command(tmp_path) == ["flutter", "test"]
    (tmp_path / "pubspec.yaml").write_text("name: x\ndependencies:\n  args: ^2.0.0\n", encoding="utf-8")
    assert testrun.test_command(tmp_path) == ["dart", "test"]


def test_gradlew_preferred_when_present(tmp_path):
    (tmp_path / "build.gradle").write_text("x", encoding="utf-8")
    (tmp_path / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    cmd = testrun.test_command(tmp_path)
    assert cmd[0].endswith("gradlew") and cmd[1] == "test"


def test_no_manifest_returns_none(tmp_path):
    assert testrun.test_command(tmp_path) is None
