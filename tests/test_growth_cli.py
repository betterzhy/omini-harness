from __future__ import annotations

import copy
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


def _repository_root() -> Path:
    return Path(__file__).parents[1]


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/var/empty",
            "XDG_CONFIG_HOME": "/var/empty",
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    return completed.stdout.strip()


def _commit_all(root: Path) -> tuple[str, str]:
    _git(root, "add", "--all")
    subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "user.name=Harness Test",
            "-c",
            "user.email=harness@example.invalid",
            "commit",
            "-q",
            "-m",
            "growth CLI fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")


def _filesystem_snapshot(root: Path) -> dict[str, tuple[Any, ...]]:
    if not root.exists():
        return {"<absent>": ()}
    snapshot: dict[str, tuple[Any, ...]] = {}
    ignored_tool_roots = {".git", ".idea", ".vscode"}

    def visit(directory: Path) -> None:
        for entry in sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name)):
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            relative_path = Path(relative)
            if (
                relative_path.parts[0] in ignored_tool_roots
                or relative_path.name == ".DS_Store"
                or relative_path.name.startswith("._")
            ):
                continue
            current = entry.stat(follow_symlinks=False)
            mode = stat.S_IMODE(current.st_mode)
            if stat.S_ISLNK(current.st_mode):
                snapshot[relative] = ("symlink", mode, os.readlink(path))
            elif stat.S_ISDIR(current.st_mode):
                snapshot[relative] = ("directory", mode)
                visit(path)
            elif stat.S_ISREG(current.st_mode):
                snapshot[relative] = ("file", mode, path.read_bytes())
            else:
                snapshot[relative] = ("other", current.st_mode, current.st_rdev)

    visit(root)
    return snapshot


def _git_probe(root: Path) -> dict[str, bytes | str]:
    return {
        "head": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "status": _git(root, "status", "--porcelain=v2", "--untracked-files=all"),
        "index": Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "index")).read_bytes(),
        "head-file": Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "HEAD")).read_bytes(),
    }


def _run_cli(
    root: Path,
    *arguments: str,
    stdin: str | None = None,
    environment: dict[str, str] | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    current = os.environ.copy()
    current["PYTHONPATH"] = str(_repository_root() / "src")
    if environment:
        current.update(environment)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evolution_harness.cli",
            "--repository-root",
            str(root),
            *arguments,
        ],
        input=stdin,
        text=True,
        capture_output=True,
        env=current,
        timeout=timeout,
    )


def _registered_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    from evolution_harness.authority import build_authority_snapshot
    from evolution_harness.registration import load_project_registration

    source = tmp_path / "registered-source"
    shutil.copytree(_repository_root() / "examples/external-project-source", source)
    _git(source, "init", "-q")
    _commit_all(source)
    loaded = load_project_registration(_repository_root(), source)
    snapshot = build_authority_snapshot(
        _repository_root(), loaded["integrationRoot"], source
    )
    assert snapshot["gate"] == "PASS"
    authority = next(item for item in snapshot["authorities"] if item["path"] == "status.md")
    request = {
        "schemaVersion": "growth-assessment-request/v1",
        "policyVersion": "growth-assessment-policy/v1",
        "source": {
            "sourceKind": "REGISTERED_PROJECT",
            "projectId": loaded["integration"]["config"]["projectId"],
            "integrationId": loaded["registration"]["integrationId"],
            "runtime": loaded["registration"]["runtime"],
            "sourceRevision": {
                key: snapshot["sourceRevision"][key] for key in ("kind", "head", "tree")
            },
            "authoritySnapshotFingerprint": snapshot["snapshotFingerprint"],
            "capabilityLockFingerprint": loaded["registration"]["capabilityLockFingerprint"],
        },
        "task": {
            "taskId": "hg1-task-5",
            "attemptId": "attempt-1",
            "gateId": "growth-cli",
        },
        "riskLevel": "R1",
        "trigger": "VERIFICATION_GAP",
        "projectGate": "PASS",
        "verdict": "SIGNAL",
        "reasonCodes": ["REVALIDATION_NEEDED"],
        "summary": "The registered task exposed a reusable verification gap.",
        "impact": "Future assessments need the same provenance check.",
        "capabilityHints": ["skill:agent-design:architecture-review"],
        "evidence": [
            {
                "kind": "PROJECT_ARTIFACT",
                "reference": authority["path"],
                "revision": snapshot["sourceRevision"]["head"],
                "digest": "sha256:" + authority["sha256"],
                "availability": "REPLAYABLE",
                "visibility": "PROJECT",
                "distillation": "The registered status is replayable authority.",
            }
        ],
        "assessedAt": "2026-09-02T08:00:00Z",
    }
    return source, request


def _no_signal(request: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(request)
    value["task"]["attemptId"] = "attempt-2"
    value["riskLevel"] = "R2"
    value["trigger"] = "FORMAL_CLOSURE"
    value["verdict"] = "NO_SIGNAL"
    value["reasonCodes"] = ["PROJECT_LOCAL_ONLY"]
    value["summary"] = "No transferable pattern was found."
    value["impact"] = ""
    value["capabilityHints"] = []
    value["evidence"] = []
    return value


def _growth_arguments(source: Path, state: Path, request: str = "-") -> list[str]:
    return [
        "growth",
        "assess",
        "--source",
        str(source),
        "--request",
        request,
        "--state-root",
        str(state),
        "--format",
        "json",
    ]


def _assert_error(
    result: subprocess.CompletedProcess[str],
    *,
    command: str,
    code: str,
    capture_gate: bool = False,
) -> dict[str, Any]:
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "harness-cli/v1"
    assert payload["ok"] is False
    assert payload["command"] == command
    assert payload["data"]["code"] == code
    expected = {"code", "message", "growthCaptureGate"} if capture_gate else {"code", "message"}
    assert set(payload["data"]) == expected
    if capture_gate:
        assert payload["data"]["growthCaptureGate"] == "FAIL"
    return payload


@pytest.mark.parametrize(
    ("arguments", "command"),
    [
        (["growth"], "growth"),
        (["growth", "unknown"], "growth"),
        (["growth", "assess"], "growth assess"),
        (["growth", "receipt"], "growth receipt"),
        (["growth", "scan"], "growth scan"),
        (["growth", "scan", "--as-of", "2026-09-02T09:00:00Z", "--format", "text"], "growth scan"),
        (["growth", "scan", "--as-of", "2026-09-02T09:00:00Z", "--format", "json", "--format", "json"], "growth scan"),
        (["growth", "scan", "--as-of", "2026-09-02T09:00:00Z", "--forma", "json"], "growth scan"),
        (["growth", "receipt", "--id", "growth-assessment:" + "a" * 24, "--check", "--format", "json", "--unknown"], "growth receipt"),
    ],
)
def test_growth_argument_failures_are_exact_json_and_write_nothing(
    tmp_path: Path, arguments: list[str], command: str
):
    state = tmp_path / "state"
    before_harness = _filesystem_snapshot(_repository_root())
    before_git = _git_probe(_repository_root())

    result = _run_cli(_repository_root(), *arguments)

    assert json.loads(result.stdout) == {
        "schemaVersion": "harness-cli/v1",
        "ok": False,
        "command": command,
        "data": {
            "code": "GROWTH_ARGUMENT_INVALID",
            "message": "invalid growth command arguments",
        },
    }
    assert result.returncode == 1
    assert result.stderr == ""
    assert not state.exists()
    assert before_harness == _filesystem_snapshot(_repository_root())
    assert before_git == _git_probe(_repository_root())


@pytest.mark.parametrize("serialization", ["json", "yaml"])
def test_growth_assess_stdin_records_registered_r1_signal_without_source_or_harness_writes(
    tmp_path: Path, serialization: str
):
    from evolution_harness.schema import SchemaStore

    source, request = _registered_fixture(tmp_path)
    state = tmp_path / "state"
    document = json.dumps(request) if serialization == "json" else yaml.safe_dump(request, sort_keys=False)
    before_source = _filesystem_snapshot(source)
    before_source_git = _git_probe(source)
    before_harness = _filesystem_snapshot(_repository_root())
    before_harness_git = _git_probe(_repository_root())

    result = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=document
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "growth assess"
    assert payload["data"]["status"] == "RECORDED"
    assert payload["data"]["growthCaptureGate"] == "PASS"
    assert payload["data"]["receipt"]["assessment"]["riskLevel"] == "R1"
    assert payload["data"]["receipt"]["assessment"]["verdict"] == "SIGNAL"
    SchemaStore(_repository_root()).validate(
        "core/schemas/growth-capture-result.schema.json", payload["data"]
    )
    assert len(list((state / "inbox").iterdir())) == 1
    assert before_source == _filesystem_snapshot(source)
    assert before_source_git == _git_probe(source)
    assert before_harness == _filesystem_snapshot(_repository_root())
    assert before_harness_git == _git_probe(_repository_root())


def test_explicit_request_file_records_r2_no_signal_and_is_never_changed(tmp_path: Path):
    source, signal = _registered_fixture(tmp_path)
    request = _no_signal(signal)
    state = tmp_path / "state"
    request_directory = tmp_path / "requests"
    request_directory.mkdir()
    request_path = request_directory / "assessment.yaml"
    request_path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")
    before = _filesystem_snapshot(request_directory)

    result = _run_cli(
        _repository_root(),
        *_growth_arguments(source, state, str(request_path)),
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["data"]["status"] == "RECORDED"
    assert payload["data"]["receipt"]["assessment"]["riskLevel"] == "R2"
    assert payload["data"]["receipt"]["assessment"]["verdict"] == "NO_SIGNAL"
    assert before == _filesystem_snapshot(request_directory)


def test_exact_replay_is_duplicate_and_conflict_preserves_winner(tmp_path: Path):
    source, request = _registered_fixture(tmp_path)
    state = tmp_path / "state"
    arguments = _growth_arguments(source, state)
    first = _run_cli(_repository_root(), *arguments, stdin=json.dumps(request))
    first_payload = json.loads(first.stdout)["data"]
    winner = next((state / "inbox").iterdir())
    winner_bytes = winner.read_bytes()
    before = _filesystem_snapshot(state)

    duplicate = _run_cli(_repository_root(), *arguments, stdin=json.dumps(request))

    assert duplicate.returncode == 0
    duplicate_data = json.loads(duplicate.stdout)["data"]
    assert duplicate_data["status"] == "DUPLICATE"
    assert duplicate_data["assessmentId"] == first_payload["assessmentId"]
    assert duplicate_data["requestDigest"] == first_payload["requestDigest"]
    assert _filesystem_snapshot(state) == before
    conflict = copy.deepcopy(request)
    conflict["summary"] = "This conflicts with the winning assessment."
    failed = _run_cli(_repository_root(), *arguments, stdin=json.dumps(conflict))
    _assert_error(
        failed,
        command="growth assess",
        code="ASSESSMENT_KEY_CONFLICT",
        capture_gate=True,
    )
    assert winner.read_bytes() == winner_bytes
    assert len(list((state / "inbox").iterdir())) == 1


def test_assess_deferred_results_are_typed_and_retry_bound(tmp_path: Path):
    from evolution_harness.schema import SchemaStore

    source, request = _registered_fixture(tmp_path)
    missing_home = _run_cli(
        _repository_root(),
        "growth",
        "assess",
        "--source",
        str(source),
        "--request",
        "-",
        "--format",
        "json",
        stdin=json.dumps(request),
        environment={"CODEX_HOME": ""},
    )
    assert missing_home.returncode == 1
    unavailable = json.loads(missing_home.stdout)["data"]
    assert unavailable["growthCaptureGate"] == "DEFERRED"
    assert unavailable["deferredReason"] == "STATE_ROOT_UNAVAILABLE"
    assert unavailable["retryInstruction"] == {
        "command": "growth assess",
        "requiresSameRequestDigest": True,
        "requiresSameSourceContext": True,
    }
    SchemaStore(_repository_root()).validate(
        "core/schemas/growth-capture-result.schema.json", unavailable
    )

    state = tmp_path / "state"
    recorded = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(request)
    )
    expected = json.loads(recorded.stdout)["data"]
    lock_descriptor = os.open(state / "locks/inbox.lock", os.O_RDWR)
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = _run_cli(
            _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(request)
        )
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
    assert locked.returncode == 1
    deferred = json.loads(locked.stdout)["data"]
    assert deferred["deferredReason"] == "INBOX_LOCKED"
    assert deferred["assessmentKey"] == expected["assessmentKey"]
    assert deferred["assessmentId"] == expected["assessmentId"]
    assert deferred["requestDigest"] == expected["requestDigest"]
    SchemaStore(_repository_root()).validate(
        "core/schemas/growth-capture-result.schema.json", deferred
    )


@pytest.mark.parametrize(
    "document",
    [
        "schemaVersion: growth-assessment-request/v1\nschemaVersion: duplicate\n",
        "value: &anchor secret\ncopy: *anchor\n",
        "base: &base {value: secret}\nmerged: {<<: *base}\n",
        "{1: non-string-key}\n",
        "- non-object\n",
        "{}\n---\n{}\n",
        "{}\ntrailing: [\n",
    ],
)
def test_strict_request_reader_rejects_ambiguous_yaml_without_state_creation(
    tmp_path: Path, document: str
):
    source, _ = _registered_fixture(tmp_path)
    state = tmp_path / "state"

    result = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=document
    )

    _assert_error(
        result,
        command="growth assess",
        code="ASSESSMENT_SCHEMA_INVALID",
        capture_gate=True,
    )
    assert not state.exists()


def test_request_size_symlink_and_relative_paths_fail_before_access(tmp_path: Path):
    source, request = _registered_fixture(tmp_path)
    state = tmp_path / "state"
    oversized = json.dumps(request) + (" " * 70_000)
    result = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=oversized
    )
    _assert_error(
        result,
        command="growth assess",
        code="ASSESSMENT_SCHEMA_INVALID",
        capture_gate=True,
    )
    assert not state.exists()

    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    alias = tmp_path / "alias.json"
    alias.symlink_to(request_path)
    symlinked = _run_cli(
        _repository_root(), *_growth_arguments(source, state, str(alias))
    )
    _assert_error(
        symlinked,
        command="growth assess",
        code="ASSESSMENT_SCHEMA_INVALID",
        capture_gate=True,
    )
    relative = _run_cli(
        _repository_root(),
        "growth",
        "assess",
        "--source",
        "relative-source",
        "--request",
        "relative-request.yaml",
        "--state-root",
        "relative-state",
        "--format",
        "json",
    )
    _assert_error(relative, command="growth assess", code="GROWTH_ARGUMENT_INVALID")
    assert not state.exists()


def test_explicit_request_non_regular_file_is_rejected_without_blocking(tmp_path: Path):
    source, _ = _registered_fixture(tmp_path)
    state = tmp_path / "state"
    request_fifo = tmp_path / "request.fifo"
    os.mkfifo(request_fifo, 0o600)

    result = _run_cli(
        _repository_root(),
        *_growth_arguments(source, state, str(request_fifo)),
        timeout=2,
    )

    _assert_error(
        result,
        command="growth assess",
        code="ASSESSMENT_SCHEMA_INVALID",
        capture_gate=True,
    )
    assert not state.exists()


def test_receipt_and_scan_are_read_only_typed_and_do_not_load_source(tmp_path: Path):
    source, signal = _registered_fixture(tmp_path)
    state = tmp_path / "state"
    first = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(signal)
    )
    first_data = json.loads(first.stdout)["data"]
    no_signal = _no_signal(signal)
    second = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(no_signal)
    )
    second_data = json.loads(second.stdout)["data"]
    shutil.rmtree(source / ".agent-evolution")
    before = _filesystem_snapshot(state)

    receipt = _run_cli(
        _repository_root(),
        "growth",
        "receipt",
        "--id",
        first_data["assessmentId"],
        "--state-root",
        str(state),
        "--check",
        "--format",
        "json",
    )
    scan = _run_cli(
        _repository_root(),
        "growth",
        "scan",
        "--as-of",
        "2026-09-02T09:00:00+01:00",
        "--state-root",
        str(state),
        "--format",
        "json",
    )

    assert receipt.returncode == 0
    receipt_payload = json.loads(receipt.stdout)
    assert receipt_payload["data"]["assessmentId"] == first_data["assessmentId"]
    assert receipt_payload["data"]["status"] == "RECORDED"
    assert scan.returncode == 0
    report = json.loads(scan.stdout)["data"]
    assert report["asOf"] == "2026-09-02T08:00:00Z"
    assert report["counts"] == {
        "totalEntries": 2,
        "validRecords": 2,
        "invalidRecords": 0,
        "signal": 1,
        "noSignal": 1,
        "humanTriageRequired": 1,
        "noAction": 1,
    }
    dispositions = {record["assessmentId"]: record["disposition"] for record in report["records"]}
    assert dispositions == {
        first_data["assessmentId"]: "HUMAN_TRIAGE_REQUIRED",
        second_data["assessmentId"]: "NO_ACTION",
    }
    assert _filesystem_snapshot(state) == before


@pytest.mark.parametrize("action", ["receipt", "scan"])
def test_read_only_commands_do_not_create_missing_state(tmp_path: Path, action: str):
    state = tmp_path / "missing-state"
    if action == "receipt":
        arguments = [
            "growth",
            "receipt",
            "--id",
            "growth-assessment:" + "a" * 24,
            "--state-root",
            str(state),
            "--check",
            "--format",
            "json",
        ]
    else:
        arguments = [
            "growth",
            "scan",
            "--as-of",
            "2026-09-02T08:00:00Z",
            "--state-root",
            str(state),
            "--format",
            "json",
        ]
    result = _run_cli(_repository_root(), *arguments)
    _assert_error(
        result,
        command=f"growth {action}",
        code="STATE_ROOT_UNAVAILABLE",
    )
    assert not state.exists()


def test_assess_failures_are_not_deferred_and_do_not_leak_request(tmp_path: Path):
    source, request = _registered_fixture(tmp_path)
    state = tmp_path / "state"
    mismatch = copy.deepcopy(request)
    mismatch["source"]["projectId"] = "secret-project-sentinel"
    result = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(mismatch)
    )
    payload = _assert_error(
        result,
        command="growth assess",
        code="SOURCE_CONTEXT_MISMATCH",
        capture_gate=True,
    )
    assert "secret-project-sentinel" not in payload["data"]["message"]
    assert not state.exists()

    recorded = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(request)
    )
    assert recorded.returncode == 0
    winner = next((state / "inbox").iterdir())
    winner.write_bytes(b'{"corrupt":true}\n')
    winner.chmod(0o600)
    corrupt = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(request)
    )
    _assert_error(
        corrupt,
        command="growth assess",
        code="RECEIPT_CORRUPT",
        capture_gate=True,
    )


def test_state_root_containment_fails_before_any_state_entry(tmp_path: Path):
    source, request = _registered_fixture(tmp_path)
    forbidden = [source / "state", _repository_root() / ".task5-forbidden-state"]
    unrelated = tmp_path / "unrelated-git"
    unrelated.mkdir()
    _git(unrelated, "init", "-q")
    forbidden.append(unrelated / "nested/state")
    for state in forbidden:
        result = _run_cli(
            _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(request)
        )
        _assert_error(
            result,
            command="growth assess",
            code="STATE_ROOT_UNSAFE",
            capture_gate=True,
        )
        assert not state.exists()


def test_scan_invalid_receipt_returns_typed_fail_report(tmp_path: Path):
    source, request = _registered_fixture(tmp_path)
    state = tmp_path / "state"
    recorded = _run_cli(
        _repository_root(), *_growth_arguments(source, state), stdin=json.dumps(request)
    )
    assert recorded.returncode == 0
    invalid = state / "inbox" / ("f" * 24 + ".json")
    invalid.write_bytes(b"not-json\n")
    invalid.chmod(0o600)

    result = _run_cli(
        _repository_root(),
        "growth",
        "scan",
        "--as-of",
        "2026-09-02T08:00:00Z",
        "--state-root",
        str(state),
        "--format",
        "json",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["data"]["schemaVersion"] == "growth-scan-report/v1"
    assert payload["data"]["gate"] == "FAIL"
    assert payload["data"]["counts"]["invalidRecords"] == 1


def test_existing_non_growth_parser_contract_remains_text_by_default(capsys: pytest.CaptureFixture[str]):
    from evolution_harness import cli

    with pytest.raises(SystemExit) as captured:
        cli.build_parser().parse_args(["planning", "plan"])
    assert captured.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "--request" in output.err
