from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from evolution_harness import cli
from evolution_harness.controlled_coordinator_inputs import ControlledCoordinationError


def _filesystem_snapshot(
    root: Path,
) -> dict[str, tuple[str, bytes | None, str | None]]:
    snapshot: dict[str, tuple[str, bytes | None, str | None]] = {}

    def visit(directory: Path) -> None:
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            path = Path(entry.path)
            relative_name = path.relative_to(root).as_posix()
            if entry.is_symlink():
                snapshot[relative_name] = ("symlink", None, os.readlink(path))
            elif entry.is_dir(follow_symlinks=False):
                snapshot[relative_name] = ("dir", None, None)
                visit(path)
            elif entry.is_file(follow_symlinks=False):
                snapshot[relative_name] = ("file", path.read_bytes(), None)
            else:
                raise AssertionError(f"unexpected filesystem entry: {path}")

    visit(root)
    return snapshot


@dataclass(frozen=True)
class CoordinationCliFactory:
    repository_root: Path
    source: Path
    request: Path

    def argv(self, action: str, *, request: bool = False) -> list[str]:
        result = [
            "--repository-root",
            str(self.repository_root),
            "coordination",
            action,
            "--source",
            str(self.source),
        ]
        if request:
            result.extend(["--request", str(self.request)])
        return result


@pytest.fixture
def coordination_cli_factory(tmp_path: Path, repository_root: Path):
    source = tmp_path / "registered-project"
    (source / "authority").mkdir(parents=True)
    (source / "authority" / "status.md").write_bytes(b"authority\n")
    (source / "README.md").write_bytes(b"project\n")
    (source / "current-status").symlink_to("authority/status.md")
    request = tmp_path / "request.yaml"
    request.write_text(yaml.safe_dump({"command": "fixture"}), encoding="utf-8")
    before = _filesystem_snapshot(source)
    factory = CoordinationCliFactory(repository_root, source, request)

    yield factory

    assert _filesystem_snapshot(source) == before


def _invoke(capsys, factory: CoordinationCliFactory, action: str, *, request=False):
    return_code = cli.main(factory.argv(action, request=request))
    captured = capsys.readouterr()
    assert captured.err == ""
    return return_code, json.loads(captured.out)


def _run_subprocess(factory: CoordinationCliFactory, *args: str):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(factory.repository_root / "src")
    return subprocess.run(
        [sys.executable, "-m", "evolution_harness.cli", *args],
        text=True,
        capture_output=True,
        env=environment,
    )


def test_coordination_status_invalid_registration_is_json_not_argparse_text(
    coordination_cli_factory,
):
    result = _run_subprocess(
        coordination_cli_factory,
        *coordination_cli_factory.argv("status"),
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "harness-cli/v1"
    assert payload["ok"] is False
    assert payload["command"] == "coordination status"
    assert payload["data"]["code"] == "PROJECT_EXECUTION_IDENTITY_INVALID"
    assert payload["data"]["message"]
    assert payload["data"]["data"] == {}


def test_coordination_status_reports_uninitialized_safe_state(
    coordination_cli_factory, monkeypatch, capsys
):
    expected = {
        "schemaVersion": "controlled-coordinator-status/v1",
        "projectExecutionKey": "project-execution:" + "1" * 64,
        "initialized": False,
        "journalVersion": 0,
        "nextFencingToken": 1,
        "recoveryState": "CLEAR",
        "latestReceiptId": None,
        "journalDigest": None,
        "retainedLeaseIds": [],
        "releasedLeaseIds": [],
        "leases": [],
    }
    monkeypatch.setattr(cli, "inspect_project_coordinator", lambda *_: expected)

    return_code, payload = _invoke(
        capsys, coordination_cli_factory, "status"
    )

    assert return_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "coordination status"
    assert payload["data"] == {
        "code": "OK",
        "message": "coordinator safety status inspected",
        "data": expected,
    }


@pytest.mark.parametrize(
    ("action", "api_name", "result", "expected"),
    [
        (
            "acquire",
            "acquire_lane_lease",
            {
                "schemaVersion": "controlled-execution-lease/v1",
                "leaseId": "lease:" + "1" * 24,
                "fencingToken": 7,
                "state": "ADMITTED",
                "released": False,
                "recoveryStatus": "CLEAR",
            },
            {"fencingToken": 7, "released": False, "recoveryStatus": "CLEAR"},
        ),
        (
            "transition",
            "transition_lane_lease",
            {
                "leaseId": "lease:" + "1" * 24,
                "fencingToken": 7,
                "state": "BLOCKED",
                "released": False,
                "leaseRetained": True,
                "recoveryStatus": "CLEAR",
            },
            {"fencingToken": 7, "leaseRetained": True, "released": False},
        ),
        (
            "observe",
            "observe_lane_writes",
            {
                "receiptId": "coordinator-receipt:" + "2" * 24,
                "journalVersion": 2,
                "recoveryState": "PROJECT_WRITESET_RECOVERY",
                "observedWriteSet": ["undeclared.txt"],
                "revokedLeaseIds": ["lease:" + "1" * 24],
                "affectedLeaseDecisions": [],
            },
            {
                "receiptId": "coordinator-receipt:" + "2" * 24,
                "journalVersion": 2,
                "recoveryState": "PROJECT_WRITESET_RECOVERY",
            },
        ),
        (
            "recover",
            "record_project_recovery",
            {
                "receiptId": "coordinator-receipt:" + "3" * 24,
                "journalVersion": 3,
                "recoveryState": "CLEAR",
                "observedWriteSet": ["undeclared.txt"],
                "releasedLeaseIds": ["lease:" + "1" * 24],
                "affectedLeaseDecisions": [],
            },
            {
                "receiptId": "coordinator-receipt:" + "3" * 24,
                "journalVersion": 3,
                "recoveryState": "CLEAR",
                "releasedLeaseIds": ["lease:" + "1" * 24],
            },
        ),
    ],
)
def test_mutating_coordination_commands_dispatch_request_and_emit_relevant_safety_data(
    coordination_cli_factory,
    monkeypatch,
    capsys,
    action,
    api_name,
    result,
    expected,
):
    calls = []

    def fake_api(repository_root, source_root, request):
        calls.append((repository_root, source_root, request))
        return result

    monkeypatch.setattr(cli, api_name, fake_api)

    return_code, payload = _invoke(
        capsys, coordination_cli_factory, action, request=True
    )

    assert return_code == 0
    assert calls == [
        (
            coordination_cli_factory.repository_root,
            coordination_cli_factory.source,
            {"command": "fixture"},
        )
    ]
    assert payload["data"]["code"] == "OK"
    assert payload["data"]["message"]
    for key, value in expected.items():
        assert payload["data"]["data"][key] == value


def test_coordination_acquire_exact_replay_is_preserved(
    coordination_cli_factory, monkeypatch, capsys
):
    lease = {
        "schemaVersion": "controlled-execution-lease/v1",
        "leaseId": "lease:" + "4" * 24,
        "fencingToken": 11,
        "state": "ADMITTED",
        "released": False,
        "recoveryStatus": "CLEAR",
    }
    calls = []

    def replay(*args):
        calls.append(args)
        return lease

    monkeypatch.setattr(cli, "acquire_lane_lease", replay)

    first_code, first = _invoke(
        capsys, coordination_cli_factory, "acquire", request=True
    )
    second_code, second = _invoke(
        capsys, coordination_cli_factory, "acquire", request=True
    )

    assert first_code == second_code == 0
    assert first == second
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("action", "api_name", "code"),
    [
        ("acquire", "acquire_lane_lease", "LIVE_AUTHORITY_SNAPSHOT_MISMATCH"),
        ("acquire", "acquire_lane_lease", "COORDINATOR_LOCK_BUSY"),
        ("acquire", "acquire_lane_lease", "PROTECTED_ACTION_DENIED"),
        ("transition", "transition_lane_lease", "COORDINATOR_RECOVERY_REQUIRED"),
    ],
)
def test_coordination_errors_preserve_closed_json_codes(
    coordination_cli_factory, monkeypatch, capsys, action, api_name, code
):
    def fail(*_):
        raise ControlledCoordinationError(code, f"closed: {code}")

    monkeypatch.setattr(cli, api_name, fail)

    return_code, payload = _invoke(
        capsys, coordination_cli_factory, action, request=True
    )

    assert return_code == 1
    assert payload["ok"] is False
    assert payload["data"] == {
        "code": code,
        "message": f"closed: {code}",
        "data": {},
    }


def test_coordination_status_exposes_recovery_pending_without_mutation(
    coordination_cli_factory, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli,
        "inspect_project_coordinator",
        lambda *_: {
            "schemaVersion": "controlled-coordinator-status/v1",
            "projectExecutionKey": "project-execution:" + "1" * 64,
            "initialized": True,
            "journalVersion": 2,
            "nextFencingToken": 9,
            "recoveryState": "PROJECT_WRITESET_RECOVERY",
            "latestReceiptId": "coordinator-receipt:" + "5" * 24,
            "journalDigest": "sha256:" + "6" * 64,
            "retainedLeaseIds": ["lease:" + "7" * 24],
            "releasedLeaseIds": [],
            "leases": [],
        },
    )

    return_code, payload = _invoke(capsys, coordination_cli_factory, "status")

    assert return_code == 0
    assert payload["data"]["data"]["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
    assert payload["data"]["data"]["latestReceiptId"] == (
        "coordinator-receipt:" + "5" * 24
    )
    assert payload["data"]["data"]["journalVersion"] == 2


def test_coordination_parser_requires_explicit_inputs_and_has_no_execution_options(
    coordination_cli_factory,
):
    parser = cli.build_parser()
    required_failures = [
        ["coordination", "status"],
        ["coordination", "acquire", "--source", str(coordination_cli_factory.source)],
        ["coordination", "transition", "--request", str(coordination_cli_factory.request)],
        ["coordination", "observe", "--source", str(coordination_cli_factory.source)],
        ["coordination", "recover", "--request", str(coordination_cli_factory.request)],
    ]
    for argv in required_failures:
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(argv)
        assert caught.value.code == 2

    forbidden = [
        "--apply",
        "--agent",
        "--launch",
        "--launch-agent",
        "--worktree",
        "--create-worktree",
        "--ref",
        "--git-ref",
        "--merge",
        "--push",
        "--authority",
        "--mutate-authority",
        "--format",
    ]
    for option in forbidden:
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(
                coordination_cli_factory.argv("acquire", request=True) + [option]
            )
        assert caught.value.code == 2

    for action in (
        "launch",
        "create-worktree",
        "integrate",
        "git-ref",
        "merge",
        "push",
        "mutate-authority",
    ):
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(["coordination", action])
        assert caught.value.code == 2
