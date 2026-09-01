from __future__ import annotations

import copy
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


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


def _commit_all(root: Path, message: str = "fixture") -> tuple[str, str]:
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
            message,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")


def _snapshot_entries(root: Path) -> dict[str, tuple[Any, ...]]:
    snapshot: dict[str, tuple[Any, ...]] = {}

    def visit(directory: Path) -> None:
        for entry in sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name)):
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
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


def _call_unchanged(
    repository_root: Path,
    source_root: Path,
    request: dict[str, Any],
    *,
    expected_code: str | None = None,
) -> dict[str, Any] | None:
    from evolution_harness.growth_assessment import GrowthAssessmentError
    from evolution_harness.growth_source import validate_growth_source

    physical_source = source_root.resolve(strict=True)
    before_source = _snapshot_entries(physical_source)
    before_request = copy.deepcopy(request)
    if expected_code is None:
        result = validate_growth_source(repository_root, source_root, request)
    else:
        with pytest.raises(GrowthAssessmentError) as caught:
            validate_growth_source(repository_root, source_root, request)
        assert caught.value.code == expected_code
        result = None
    assert request == before_request
    assert _snapshot_entries(physical_source) == before_source
    return result


def _harness_fixture(tmp_path: Path) -> Path:
    repository = Path(__file__).parents[1]
    root = tmp_path / "harness"
    for name in ("core", "design", "runtime"):
        shutil.copytree(repository / name, root / name)
    (root / "integrations").mkdir()
    shutil.copytree(
        repository / "integrations/neutral-shadow",
        root / "integrations/neutral-shadow",
    )
    return root


def _registered_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    from evolution_harness.authority import build_authority_snapshot
    from evolution_harness.registration import load_project_registration

    repository = Path(__file__).parents[1]
    harness = _harness_fixture(tmp_path)
    source = tmp_path / "registered-source"
    shutil.copytree(repository / "examples/external-project-source", source)
    (source / "temp-input").mkdir()
    (source / "temp-input/poison.txt").write_text(
        "excluded bytes must never be read\n", encoding="utf-8"
    )
    integration_path = harness / "integrations/neutral-shadow/integration.yaml"
    integration = yaml.safe_load(integration_path.read_text(encoding="utf-8"))
    integration["excludedPaths"].append("temp-input/**")
    _write_yaml(integration_path, integration)
    _git(source, "init", "-q")
    _commit_all(source)

    loaded = load_project_registration(harness, source)
    snapshot = build_authority_snapshot(harness, loaded["integrationRoot"], source)
    assert snapshot["gate"] == "PASS"
    assert snapshot["sourceRevision"]["authoritySetStatus"] == "CLEAN_FOR_AUTHORITY_SET"
    record = next(
        item for item in snapshot["authorities"] if item["path"] == "status.md"
    )
    request = _request(
        source={
            "sourceKind": "REGISTERED_PROJECT",
            "projectId": loaded["integration"]["config"]["projectId"],
            "integrationId": loaded["registration"]["integrationId"],
            "runtime": loaded["registration"]["runtime"],
            "sourceRevision": {
                key: snapshot["sourceRevision"][key] for key in ("kind", "head", "tree")
            },
            "authoritySnapshotFingerprint": snapshot["snapshotFingerprint"],
            "capabilityLockFingerprint": loaded["registration"][
                "capabilityLockFingerprint"
            ],
        },
        evidence=[
            {
                "kind": "PROJECT_ARTIFACT",
                "reference": record["path"],
                "revision": snapshot["sourceRevision"]["head"],
                "digest": "sha256:" + record["sha256"],
                "availability": "REPLAYABLE",
                "visibility": "PROJECT",
                "distillation": "The registered authority supplies the project status.",
            }
        ],
    )
    return harness, source, request, snapshot


def _request(*, source: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "growth-assessment-request/v1",
        "policyVersion": "growth-assessment-policy/v1",
        "source": source,
        "task": {
            "taskId": "task:growth-source",
            "attemptId": "attempt:1",
            "gateId": "gate:source",
        },
        "riskLevel": "R1",
        "trigger": "VERIFICATION_GAP",
        "projectGate": "PASS",
        "verdict": "SIGNAL",
        "reasonCodes": ["REVALIDATION_NEEDED"],
        "summary": "Source provenance must remain replayable.",
        "impact": "The receipt remains bound to validated source bytes.",
        "capabilityHints": [],
        "evidence": evidence,
        "assessedAt": "2026-09-01T12:30:45Z",
    }


def _authority_paths(harness: Path) -> set[str]:
    value = yaml.safe_load(
        (harness / "integrations/neutral-shadow/authority-map.yaml").read_text(
            encoding="utf-8"
        )
    )
    return {item["path"] for item in value["authorities"]}


def test_registered_source_accepts_exact_live_provenance_and_reads_only_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evolution_harness.anchored_fs import AnchoredRoot

    harness, source, request, _ = _registered_fixture(tmp_path)
    original_read = AnchoredRoot.read_bytes
    source_reads: list[str] = []

    def observed_read(filesystem: AnchoredRoot, relative: str) -> bytes:
        if filesystem.root == source:
            source_reads.append(relative)
        return original_read(filesystem, relative)

    monkeypatch.setattr(AnchoredRoot, "read_bytes", observed_read)
    result = _call_unchanged(harness, source, request)

    assert result == request["source"]
    assert result is not request["source"]
    assert set(source_reads) == {
        ".agent-evolution/registration.yaml",
        *_authority_paths(harness),
    }
    assert "private/secret.md" not in source_reads
    assert "temp-input/poison.txt" not in source_reads


def test_registered_source_rejects_missing_registration_without_source_changes(
    tmp_path: Path,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    (source / ".agent-evolution/registration.yaml").unlink()

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_REGISTRATION_INVALID",
    )


def test_registered_source_rejects_explicit_source_symlink_without_source_changes(
    tmp_path: Path,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    alias = tmp_path / "registered-source-link"
    alias.symlink_to(source, target_is_directory=True)

    _call_unchanged(
        harness,
        alias,
        request,
        expected_code="SOURCE_REGISTRATION_INVALID",
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("projectId", "other-project", "SOURCE_CONTEXT_MISMATCH"),
        ("integrationId", "other-integration", "SOURCE_CONTEXT_MISMATCH"),
        ("runtime", "CHATGPT", "SOURCE_CONTEXT_MISMATCH"),
        (
            "capabilityLockFingerprint",
            "sha256:" + "f" * 64,
            "SOURCE_LOCK_MISMATCH",
        ),
    ],
)
def test_registered_source_rejects_request_context_and_lock_mismatch(
    tmp_path: Path,
    field: str,
    value: str,
    code: str,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    request["source"][field] = value

    _call_unchanged(harness, source, request, expected_code=code)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("integrationId", "different-integration"),
        ("runtime", "CHATGPT"),
        ("capabilityLockFingerprint", "sha256:" + "0" * 64),
    ],
)
def test_registered_source_rejects_registration_integration_runtime_and_lock_drift(
    tmp_path: Path,
    field: str,
    value: str,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    registration_path = source / ".agent-evolution/registration.yaml"
    registration = yaml.safe_load(registration_path.read_text(encoding="utf-8"))
    registration[field] = value
    _write_yaml(registration_path, registration)

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_REGISTRATION_INVALID",
    )


def test_registered_source_rejects_dirty_live_authority_without_source_changes(
    tmp_path: Path,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    status_path = source / "status.md"
    status_path.write_bytes(status_path.read_bytes() + b"\nProjectDrift = YES\n")

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_AUTHORITY_NO_GO",
    )


def test_registered_source_rejects_missing_authority_without_source_changes(
    tmp_path: Path,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    (source / "status.md").unlink()

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_AUTHORITY_NO_GO",
    )


def test_registered_source_rejects_excluded_authority_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evolution_harness.anchored_fs import AnchoredRoot

    harness, source, request, _ = _registered_fixture(tmp_path)
    authority_path = harness / "integrations/neutral-shadow/authority-map.yaml"
    authority_map = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
    authority_map["authorities"][0]["path"] = "temp-input/poison.txt"
    _write_yaml(authority_path, authority_map)
    original_read = AnchoredRoot.read_bytes
    source_reads: list[str] = []

    def rejecting_excluded_read(filesystem: AnchoredRoot, relative: str) -> bytes:
        if filesystem.root == source:
            source_reads.append(relative)
            assert not relative.startswith("temp-input/")
        return original_read(filesystem, relative)

    monkeypatch.setattr(AnchoredRoot, "read_bytes", rejecting_excluded_read)
    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_AUTHORITY_NO_GO",
    )
    assert "temp-input/poison.txt" not in source_reads


def test_registered_source_rejects_symlinked_authority_without_following_it(
    tmp_path: Path,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    outside = tmp_path / "outside-status.md"
    outside.write_text("ProjectStage = DELIVERY\n", encoding="utf-8")
    (source / "status.md").unlink()
    (source / "status.md").symlink_to(outside)

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_AUTHORITY_NO_GO",
    )
    assert outside.read_text(encoding="utf-8") == "ProjectStage = DELIVERY\n"


def test_registered_source_rejects_prior_authority_snapshot_fingerprint(
    tmp_path: Path,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    request["source"]["authoritySnapshotFingerprint"] = "sha256:" + "0" * 64

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_AUTHORITY_NO_GO",
    )


@pytest.mark.parametrize("field", ["head", "tree"])
def test_registered_source_rejects_live_revision_mismatch(
    tmp_path: Path,
    field: str,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    request["source"]["sourceRevision"][field] = "f" * 40

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_REVISION_MISMATCH",
    )


def test_registered_source_classifies_clean_non_authority_head_drift_as_revision_mismatch(
    tmp_path: Path,
):
    harness, source, request, _ = _registered_fixture(tmp_path)
    (source / "non-authority.txt").write_text(
        "tracked but outside the Authority allowlist\n",
        encoding="utf-8",
    )
    _commit_all(source, "move head outside authority set")

    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_REVISION_MISMATCH",
    )


def _mutate_replayable_case(
    case: str,
    harness: Path,
    request: dict[str, Any],
    snapshot: dict[str, Any],
) -> None:
    evidence = request["evidence"][0]
    if case == "absent":
        evidence["reference"] = "reports/absent.json"
    elif case == "duplicate":
        authority_path = harness / "integrations/neutral-shadow/authority-map.yaml"
        authority_map = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
        duplicate = copy.deepcopy(
            next(
                item
                for item in authority_map["authorities"]
                if item["path"] == evidence["reference"]
            )
        )
        duplicate["id"] = "duplicate-status-path"
        duplicate["owns"] = []
        duplicate["selectors"] = {}
        authority_map["authorities"].append(duplicate)
        _write_yaml(authority_path, authority_map)
    elif case == "derived-only":
        record = next(
            item
            for item in snapshot["authorities"]
            if item["path"] == "reports/status-summary.json"
        )
        evidence["reference"] = record["path"]
        evidence["digest"] = "sha256:" + record["sha256"]
    elif case == "digest":
        evidence["digest"] = "sha256:" + "0" * 64
    elif case == "revision":
        evidence["revision"] = "f" * 40
    elif case == "dot-alias":
        evidence["reference"] = "./status.md"
    elif case == "case-alias":
        evidence["reference"] = "STATUS.md"
    else:
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "duplicate",
        "derived-only",
        "digest",
        "revision",
        "dot-alias",
        "case-alias",
    ],
)
def test_registered_source_rejects_non_exact_replayable_claims_before_extra_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
):
    from evolution_harness.anchored_fs import AnchoredRoot

    harness, source, request, snapshot = _registered_fixture(tmp_path)
    _mutate_replayable_case(case, harness, request, snapshot)
    original_read = AnchoredRoot.read_bytes
    source_reads: list[str] = []

    def observed_read(filesystem: AnchoredRoot, relative: str) -> bytes:
        if filesystem.root == source:
            source_reads.append(relative)
        return original_read(filesystem, relative)

    monkeypatch.setattr(AnchoredRoot, "read_bytes", observed_read)
    _call_unchanged(
        harness,
        source,
        request,
        expected_code="SOURCE_AUTHORITY_NO_GO",
    )
    assert set(source_reads) <= {
        ".agent-evolution/registration.yaml",
        *_authority_paths(harness),
    }


def test_registered_source_never_opens_opaque_or_excluded_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evolution_harness.anchored_fs import AnchoredRoot

    harness, source, request, _ = _registered_fixture(tmp_path)
    request["evidence"] = [
        {
            "kind": "OTHER",
            "reference": "temp-input/poison.txt",
            "revision": "opaque-revision",
            "digest": "sha256:" + "5" * 64,
            "availability": "OPAQUE",
            "visibility": "PRIVATE",
            "distillation": "The opaque reference is not a filesystem instruction.",
        }
    ]
    original_read = AnchoredRoot.read_bytes
    source_reads: list[str] = []

    def reject_non_allowlisted(filesystem: AnchoredRoot, relative: str) -> bytes:
        if filesystem.root == source:
            source_reads.append(relative)
            assert relative != "temp-input/poison.txt"
            assert relative != "private/secret.md"
        return original_read(filesystem, relative)

    monkeypatch.setattr(AnchoredRoot, "read_bytes", reject_non_allowlisted)
    _call_unchanged(harness, source, request)
    assert set(source_reads) == {
        ".agent-evolution/registration.yaml",
        *_authority_paths(harness),
    }


def _self_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    repository = tmp_path / "self-repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / "tracked.txt").write_text("tracked baseline\n", encoding="utf-8")
    head, tree = _commit_all(repository)
    (repository / "tracked.txt").write_text(
        "tracked working-tree change\n", encoding="utf-8"
    )
    (repository / "untracked.txt").write_text("untracked sentinel\n", encoding="utf-8")
    source = {
        "sourceKind": "HARNESS_SELF",
        "projectId": "agent-evolution-harness",
        "runtime": "CODEX",
        "sourceRevision": {"kind": "GIT", "head": head, "tree": tree},
    }
    return repository, _request(source=source, evidence=[])


def test_harness_self_accepts_only_same_physical_root_with_two_read_only_git_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repository, request = _self_fixture(tmp_path)
    before_status = _git(repository, "status", "--porcelain=v2", "--untracked-files=all")
    real_run = subprocess.run
    observed: list[tuple[tuple[str, ...], Path | None, dict[str, str]]] = []

    def observed_run(arguments, *args, **kwargs):
        observed.append(
            (
                tuple(arguments),
                kwargs.get("cwd"),
                dict(kwargs.get("env") or {}),
            )
        )
        return real_run(arguments, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", observed_run)
    result = _call_unchanged(repository, repository, request)

    assert result == request["source"]
    assert [item[0][1:] for item in observed] == [
        ("rev-parse", "HEAD"),
        ("rev-parse", "HEAD^{tree}"),
    ]
    assert all(item[0][0] == "/usr/bin/git" for item in observed)
    assert all(item[1] == repository for item in observed)
    assert all(item[2]["GIT_OPTIONAL_LOCKS"] == "0" for item in observed)
    assert all(item[2]["GIT_TERMINAL_PROMPT"] == "0" for item in observed)
    assert _git(repository, "status", "--porcelain=v2", "--untracked-files=all") == before_status


def test_external_unregistered_repository_cannot_claim_harness_self(
    tmp_path: Path,
):
    repository, request = _self_fixture(tmp_path)
    external = tmp_path / "external-repository"
    external.mkdir()
    _git(external, "init", "-q")
    (external / "external.txt").write_text("external\n", encoding="utf-8")
    head, tree = _commit_all(external)
    request["source"]["sourceRevision"] = {"kind": "GIT", "head": head, "tree": tree}

    _call_unchanged(
        repository,
        external,
        request,
        expected_code="SOURCE_SELF_INVALID",
    )


@pytest.mark.parametrize("field", ["head", "tree"])
def test_harness_self_rejects_head_or_tree_drift_without_repository_changes(
    tmp_path: Path,
    field: str,
):
    repository, request = _self_fixture(tmp_path)
    request["source"]["sourceRevision"][field] = "f" * 40

    _call_unchanged(
        repository,
        repository,
        request,
        expected_code="SOURCE_SELF_INVALID",
    )


def test_harness_self_rejects_partial_fixed_candidate_identity(
    tmp_path: Path,
):
    repository, request = _self_fixture(tmp_path)
    request["task"].update(
        {
            "candidate": request["source"]["sourceRevision"]["head"],
            "tree": request["source"]["sourceRevision"]["tree"],
        }
    )

    _call_unchanged(
        repository,
        repository,
        request,
        expected_code="SOURCE_SELF_INVALID",
    )


@pytest.mark.parametrize("unsafe_kind", ["symlink", "relative"])
def test_harness_self_rejects_unsafe_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
):
    repository, request = _self_fixture(tmp_path)
    if unsafe_kind == "symlink":
        source_root = tmp_path / "self-link"
        source_root.symlink_to(repository, target_is_directory=True)
    else:
        monkeypatch.chdir(tmp_path)
        source_root = Path("self-repository")

    _call_unchanged(
        repository,
        source_root,
        request,
        expected_code="SOURCE_SELF_INVALID",
    )


def test_harness_self_rejects_replayable_evidence_without_opening_reference(
    tmp_path: Path,
):
    repository, request = _self_fixture(tmp_path)
    request["evidence"] = [
        {
            "kind": "PROJECT_ARTIFACT",
            "reference": "tracked.txt",
            "revision": request["source"]["sourceRevision"]["head"],
            "digest": "sha256:" + "a" * 64,
            "availability": "REPLAYABLE",
            "visibility": "PROJECT",
            "distillation": "Self mode has no Phase 1 authority allowlist.",
        }
    ]

    _call_unchanged(
        repository,
        repository,
        request,
        expected_code="SOURCE_SELF_INVALID",
    )
