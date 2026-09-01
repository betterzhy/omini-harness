from __future__ import annotations

import copy
import gc
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from evolution_harness.growth_assessment import (
    GrowthAssessmentError,
    growth_assessment_id,
    growth_assessment_key,
    normalize_growth_assessment_request,
)


def _repository_root() -> Path:
    return Path(__file__).parents[1]


def _request(*, summary: str = "No reusable pattern was identified.", signal: bool = False) -> dict:
    evidence = []
    if signal:
        evidence = [
            {
                "kind": "FIXED_REVIEW",
                "reference": "review://growth/task-4",
                "revision": "review-1",
                "digest": "sha256:" + "7" * 64,
                "availability": "OPAQUE",
                "visibility": "PROJECT",
                "distillation": "The review found a reusable safety pattern.",
            },
            {
                "kind": "TEST_RECEIPT",
                "reference": "test://growth/task-4",
                "revision": "test-1",
                "digest": "sha256:" + "8" * 64,
                "availability": "OPAQUE",
                "visibility": "PRIVATE",
                "distillation": "The focused safety suite passed.",
            },
        ]
    return {
        "schemaVersion": "growth-assessment-request/v1",
        "policyVersion": "growth-assessment-policy/v1",
        "source": {
            "sourceKind": "HARNESS_SELF",
            "projectId": "agent-evolution-harness",
            "runtime": "CODEX",
            "sourceRevision": {"kind": "GIT", "head": "1" * 40, "tree": "2" * 40},
        },
        "task": {
            "taskId": "hg1-task-4",
            "attemptId": "attempt-1",
            "gateId": "focused-store",
        },
        "riskLevel": "R2",
        "trigger": "SECURITY_RECOVERY_OR_CONCURRENCY_FINDING",
        "projectGate": "PASS",
        "verdict": "SIGNAL" if signal else "NO_SIGNAL",
        "reasonCodes": ["REUSABLE_AGENT_BEHAVIOR"] if signal else ["PROJECT_LOCAL_ONLY"],
        "summary": summary,
        "impact": "Prevents partial or overwritten receipts." if signal else "",
        "capabilityHints": ["skill:agent-design:architecture-review"] if signal else [],
        "evidence": evidence,
        "assessedAt": "2026-09-02T08:00:00Z",
    }


def _open_for_record(state_root: Path):
    from evolution_harness.growth_store import GrowthInbox

    root = _repository_root()
    return GrowthInbox.open_for_record(root, root, state_root)


def _tree_snapshot(root: Path) -> list[tuple[str, int, int, int, bytes]]:
    if not root.exists():
        return []
    result = []
    for path in sorted(root.rglob("*")):
        current = path.lstat()
        data = path.read_bytes() if stat.S_ISREG(current.st_mode) else b""
        result.append(
            (
                path.relative_to(root).as_posix(),
                stat.S_IFMT(current.st_mode) | stat.S_IMODE(current.st_mode),
                current.st_size,
                current.st_mtime_ns,
                data,
            )
        )
    return result


def test_open_for_record_creates_only_exact_owner_only_state_layout(tmp_path: Path):
    state = tmp_path / "nested" / "explicit-state"

    _open_for_record(state)

    assert sorted(path.relative_to(state).as_posix() for path in state.rglob("*")) == [
        "inbox",
        "locks",
        "locks/inbox.lock",
        "staging",
    ]
    for directory in [state, state / "inbox", state / "staging", state / "locks"]:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert directory.stat().st_uid == os.getuid()
    lock = state / "locks" / "inbox.lock"
    assert stat.S_ISREG(lock.lstat().st_mode)
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    assert lock.stat().st_uid == os.getuid()
    assert (state / "staging").stat().st_dev == (state / "inbox").stat().st_dev


def test_default_state_root_requires_absolute_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from evolution_harness.growth_store import GrowthInbox

    root = _repository_root()
    monkeypatch.delenv("CODEX_HOME", raising=False)
    with pytest.raises(GrowthAssessmentError) as missing:
        GrowthInbox.open_for_record(root, root, None)
    assert missing.value.code == "STATE_ROOT_UNAVAILABLE"

    monkeypatch.setenv("CODEX_HOME", "relative-home")
    with pytest.raises(GrowthAssessmentError) as relative:
        GrowthInbox.open_for_record(root, root, None)
    assert relative.value.code == "STATE_ROOT_UNSAFE"
    assert not (Path.cwd() / "relative-home").exists()

    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    GrowthInbox.open_for_record(root, root, None)
    assert (codex_home / "agent-evolution" / "growth" / "v1").is_dir()


def test_relative_explicit_state_root_is_rejected_before_cwd_resolution(tmp_path: Path, monkeypatch):
    from evolution_harness.growth_store import GrowthInbox

    monkeypatch.chdir(tmp_path)
    with pytest.raises(GrowthAssessmentError) as captured:
        GrowthInbox.open_for_record(_repository_root(), _repository_root(), Path("relative-state"))
    assert captured.value.code == "STATE_ROOT_UNSAFE"
    assert not (tmp_path / "relative-state").exists()


def test_state_root_inside_harness_or_source_is_rejected_before_creation(tmp_path: Path):
    from evolution_harness.growth_store import GrowthInbox

    root = _repository_root()
    forbidden = root / ".task4-forbidden-growth-state"
    assert not forbidden.exists()
    with pytest.raises(GrowthAssessmentError) as harness_error:
        GrowthInbox.open_for_record(root, tmp_path, forbidden)
    assert harness_error.value.code == "STATE_ROOT_UNSAFE"
    assert not forbidden.exists()

    source = tmp_path / "source"
    source.mkdir()
    nested = source / "nested" / "state"
    with pytest.raises(GrowthAssessmentError) as source_error:
        GrowthInbox.open_for_record(root, source, nested)
    assert source_error.value.code == "STATE_ROOT_UNSAFE"
    assert not (source / "nested").exists()


def test_state_root_inside_linked_or_unrelated_git_worktree_is_rejected(tmp_path: Path):
    from evolution_harness.growth_store import GrowthInbox

    source = tmp_path / "source-repository"
    linked = tmp_path / "linked-worktree"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Task Four"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "task4@example.invalid"], check=True)
    (source / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "test fixture"], check=True)
    subprocess.run(["git", "-C", str(source), "worktree", "add", "-q", str(linked)], check=True)

    linked_state = linked / "state"
    with pytest.raises(GrowthAssessmentError) as linked_error:
        GrowthInbox.open_for_record(_repository_root(), source, linked_state)
    assert linked_error.value.code == "STATE_ROOT_UNSAFE"
    assert not linked_state.exists()

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    subprocess.run(["git", "init", "-q", str(unrelated)], check=True)
    unrelated_state = unrelated / "missing" / "state"
    with pytest.raises(GrowthAssessmentError) as unrelated_error:
        GrowthInbox.open_for_record(_repository_root(), source, unrelated_state)
    assert unrelated_error.value.code == "STATE_ROOT_UNSAFE"
    assert not (unrelated / "missing").exists()


def test_lexical_alias_and_symlink_ancestor_cannot_bypass_containment(tmp_path: Path):
    from evolution_harness.growth_store import GrowthInbox

    source = tmp_path / "source"
    source.mkdir()
    aliased = source / "child" / ".." / "state"
    with pytest.raises(GrowthAssessmentError) as lexical:
        GrowthInbox.open_for_record(_repository_root(), source, aliased)
    assert lexical.value.code == "STATE_ROOT_UNSAFE"
    assert not (source / "state").exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(GrowthAssessmentError) as symlinked:
        GrowthInbox.open_for_record(_repository_root(), source, alias / "state")
    assert symlinked.value.code == "STATE_ROOT_UNSAFE"
    assert not (outside / "state").exists()


@pytest.mark.parametrize(
    "unsafe_kind", ["mode", "symlink-child", "file-child", "unsafe-lock", "unexpected-child"]
)
def test_existing_unsafe_state_layout_fails_closed(tmp_path: Path, unsafe_kind: str):
    from evolution_harness.growth_store import GrowthInbox

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    if unsafe_kind == "mode":
        state.chmod(0o755)
    elif unsafe_kind == "symlink-child":
        outside = tmp_path / "outside"
        outside.mkdir()
        (state / "inbox").symlink_to(outside, target_is_directory=True)
    elif unsafe_kind == "file-child":
        (state / "staging").write_text("not a directory", encoding="utf-8")
    elif unsafe_kind == "unsafe-lock":
        for name in ("inbox", "staging", "locks"):
            (state / name).mkdir(mode=0o700)
        outside = tmp_path / "outside.lock"
        outside.write_text("sentinel", encoding="utf-8")
        (state / "locks" / "inbox.lock").symlink_to(outside)
    else:
        (state / "unexpected").write_text("must remain the only entry", encoding="utf-8")

    before = _tree_snapshot(state)
    with pytest.raises(GrowthAssessmentError) as captured:
        GrowthInbox.open_for_record(_repository_root(), _repository_root(), state)
    assert captured.value.code == "STATE_ROOT_UNSAFE"
    assert _tree_snapshot(state) == before


def test_existing_state_with_wrong_owner_is_rejected(tmp_path: Path, monkeypatch):
    from evolution_harness import growth_store

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    actual_uid = os.getuid()
    monkeypatch.setattr(growth_store.os, "getuid", lambda: actual_uid + 1)
    with pytest.raises(GrowthAssessmentError) as captured:
        growth_store.GrowthInbox.open_for_record(_repository_root(), _repository_root(), state)
    assert captured.value.code == "STATE_ROOT_UNSAFE"


def test_failed_open_never_closes_a_descriptor_reused_by_a_later_store(tmp_path: Path):
    from evolution_harness.growth_store import GrowthInbox

    unsafe = tmp_path / "unsafe-state"
    for name in ("inbox", "staging", "locks"):
        (unsafe / name).mkdir(parents=True, mode=0o700)
    referent = tmp_path / "outside.lock"
    referent.write_text("sentinel", encoding="utf-8")
    (unsafe / "locks" / "inbox.lock").symlink_to(referent)
    with pytest.raises(GrowthAssessmentError) as retained_failure:
        GrowthInbox.open_for_record(_repository_root(), _repository_root(), unsafe)

    safe = GrowthInbox.open_for_record(
        _repository_root(), _repository_root(), tmp_path / "safe-state"
    )
    del retained_failure
    gc.collect()

    assert safe.record(_request())["status"] == "RECORDED"


def test_record_persists_recorded_once_and_projects_duplicate_without_writes(tmp_path: Path):
    from evolution_harness.hashing import canonical_json_bytes

    state = tmp_path / "state"
    store = _open_for_record(state)
    request = _request()

    recorded = store.record(request)
    before = _tree_snapshot(state)
    duplicate = store.record(request)
    after = _tree_snapshot(state)

    normalized = normalize_growth_assessment_request(_repository_root(), request)
    name = growth_assessment_key(normalized).split(":", 1)[1] + ".json"
    persisted = json.loads((state / "inbox" / name).read_bytes())
    assert recorded["status"] == "RECORDED"
    assert duplicate["status"] == "DUPLICATE"
    assert persisted["status"] == "RECORDED"
    assert (state / "inbox" / name).read_bytes() == canonical_json_bytes(persisted) + b"\n"
    assert before == after
    assert len(list((state / "inbox").iterdir())) == 1


def test_conflicting_or_corrupt_existing_key_is_never_overwritten_or_repaired(tmp_path: Path):
    state = tmp_path / "state"
    store = _open_for_record(state)
    first = _request(summary="First complete assessment.")
    store.record(first)
    final = next((state / "inbox").iterdir())
    original = final.read_bytes()

    conflict = _request(summary="A conflicting assessment with the same obligation key.")
    with pytest.raises(GrowthAssessmentError) as conflict_error:
        store.record(conflict)
    assert conflict_error.value.code == "ASSESSMENT_KEY_CONFLICT"
    assert final.read_bytes() == original

    final.write_bytes(b'{"corrupt":true}\n')
    corrupt = final.read_bytes()
    with pytest.raises(GrowthAssessmentError) as corrupt_error:
        store.record(first)
    assert corrupt_error.value.code == "RECEIPT_CORRUPT"
    assert final.read_bytes() == corrupt


def test_receipt_lookup_ignores_staging_and_requires_identity_valid_published_record(tmp_path: Path):
    state = tmp_path / "state"
    store = _open_for_record(state)
    request = _request()
    recorded = store.record(request)
    (state / "staging" / "forged.json").write_bytes(b'{"assessmentId":"forged"}\n')

    found = store.receipt(recorded["assessmentId"])

    assert found == recorded
    with pytest.raises(GrowthAssessmentError) as missing:
        store.receipt("growth-assessment:" + "f" * 24)
    assert missing.value.code == "RECEIPT_NOT_FOUND"


def test_scan_reports_safe_metadata_for_all_direct_entries_and_never_writes(tmp_path: Path):
    state = tmp_path / "state"
    store = _open_for_record(state)
    signal = store.record(_request(signal=True))
    inbox = state / "inbox"
    (state / "staging" / "ignored.part").write_bytes(b"not authority")
    (inbox / "unsafe-name.txt").write_bytes(b"ignored body")
    corrupt = inbox / ("a" * 24 + ".json")
    corrupt.write_bytes(b"not-json\n")
    corrupt.chmod(0o600)
    (inbox / ("b" * 24 + ".json")).mkdir()
    (inbox / ("c" * 24 + ".json")).symlink_to(next(inbox.glob("*.json")))
    os.mkfifo(inbox / ("d" * 24 + ".json"), 0o600)
    unsafe_mode = inbox / ("e" * 24 + ".json")
    unsafe_mode.write_bytes(b"{}\n")
    unsafe_mode.chmod(0o644)
    before = _tree_snapshot(state)

    report = store.scan(as_of="2026-09-02T09:00:00+01:00")
    after = _tree_snapshot(state)

    assert before == after
    assert report["asOf"] == "2026-09-02T08:00:00Z"
    assert report["counts"] == {
        "totalEntries": 7,
        "validRecords": 1,
        "invalidRecords": 6,
        "signal": 1,
        "noSignal": 0,
        "humanTriageRequired": 1,
        "noAction": 0,
    }
    assert report["gate"] == "FAIL"
    valid = next(record for record in report["records"] if "assessmentKey" in record)
    assert valid["assessmentId"] == signal["assessmentId"]
    assert valid["visibilityCeiling"] == "PRIVATE"
    assert valid["disposition"] == "HUMAN_TRIAGE_REQUIRED"
    invalid = [record for record in report["records"] if "entryNameDigest" in record]
    assert {record["errorCode"] for record in invalid} == {"RECEIPT_UNSAFE", "RECEIPT_CORRUPT"}
    assert all(set(record) == {"entryNameDigest", "errorCode", "disposition"} for record in invalid)


def test_scan_rejects_observation_before_valid_receipt_and_entry_limit(tmp_path: Path):
    state = tmp_path / "state"
    store = _open_for_record(state)
    store.record(_request())
    with pytest.raises(GrowthAssessmentError) as timestamp:
        store.scan(as_of="2026-09-02T07:59:59Z")
    assert timestamp.value.code == "TIMESTAMP_INVALID"

    inbox = state / "inbox"
    for index in range(10000):
        (inbox / f"unsafe-{index:05d}").touch()
    with pytest.raises(GrowthAssessmentError) as limit:
        store.scan(as_of="2026-09-02T09:00:00Z")
    assert limit.value.code == "SCAN_LIMIT_EXCEEDED"


def test_open_read_only_creates_nothing_when_state_is_absent(tmp_path: Path):
    from evolution_harness.growth_store import GrowthInbox

    state = tmp_path / "absent"
    with pytest.raises(GrowthAssessmentError) as captured:
        GrowthInbox.open_read_only(_repository_root(), state)
    assert captured.value.code == "STATE_ROOT_UNAVAILABLE"
    assert not state.exists()


_RECORD_PROCESS = r"""
import json
import sys
from pathlib import Path
from evolution_harness.anchored_fs import AnchoredRoot
from evolution_harness.growth_assessment import GrowthAssessmentError
from evolution_harness.growth_store import GrowthInbox

repository = Path(sys.argv[1])
state = Path(sys.argv[2])
request = json.loads(Path(sys.argv[3]).read_text())
ready = Path(sys.argv[4]) if sys.argv[4] != "-" else None
release = Path(sys.argv[5]) if sys.argv[5] != "-" else None
if ready is not None:
    original = AnchoredRoot.publish_bytes_no_replace
    def paused(self, *args, **kwargs):
        ready.write_text("ready")
        while not release.exists():
            import time
            time.sleep(0.01)
        return original(self, *args, **kwargs)
    AnchoredRoot.publish_bytes_no_replace = paused
try:
    result = GrowthInbox.open_for_record(repository, repository, state).record(request)
    print(json.dumps({"status": result["status"], "assessmentId": result["assessmentId"]}))
except GrowthAssessmentError as exc:
    if exc.code == "INBOX_LOCKED":
        print(json.dumps({"status": "DEFERRED", "code": exc.code}))
    else:
        print(json.dumps({"status": "FAIL", "code": exc.code}))
"""


@pytest.mark.parametrize("conflict", [False, True])
def test_real_process_lock_race_defers_loser_then_replays_or_conflicts(tmp_path: Path, conflict: bool):
    repository = _repository_root()
    state = tmp_path / "state"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(_request(summary="Winner request.")), encoding="utf-8")
    second = _request(summary="Conflicting request." if conflict else "Winner request.")
    second_path.write_text(json.dumps(second), encoding="utf-8")
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "src")
    winner = subprocess.Popen(
        [sys.executable, "-c", _RECORD_PROCESS, str(repository), str(state), str(first_path), str(ready), str(release)],
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()

    loser = subprocess.run(
        [sys.executable, "-c", _RECORD_PROCESS, str(repository), str(state), str(second_path), "-", "-"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    release.write_text("release", encoding="utf-8")
    winner_output = winner.communicate(timeout=10)[0]
    retry = subprocess.run(
        [sys.executable, "-c", _RECORD_PROCESS, str(repository), str(state), str(second_path), "-", "-"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    assert json.loads(loser.stdout)["status"] == "DEFERRED"
    assert json.loads(winner_output)["status"] == "RECORDED"
    expected = {"status": "FAIL", "code": "ASSESSMENT_KEY_CONFLICT"} if conflict else {"status": "DUPLICATE"}
    retried = json.loads(retry.stdout)
    assert all(retried[key] == value for key, value in expected.items())
    assert len(list((state / "inbox").iterdir())) == 1


@pytest.mark.parametrize(
    ("crash_point", "final_expected"),
    [
        ("after_staging_create", False),
        ("mid_write", False),
        ("after_file_fsync", False),
        ("after_link", True),
        ("after_inbox_fsync", True),
        ("after_staging_unlink", True),
    ],
)
def test_growth_record_process_death_never_publishes_partial_receipt(
    tmp_path: Path, crash_point: str, final_expected: bool
):
    repository = _repository_root()
    state = tmp_path / "state"
    request = _request(summary="Process-death safety assessment.")
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    script = r"""
import json
import os
import stat
import sys
from pathlib import Path
from evolution_harness import anchored_fs
from evolution_harness.growth_store import GrowthInbox

repository = Path(sys.argv[1])
state = Path(sys.argv[2])
request = json.loads(Path(sys.argv[3]).read_text())
crash = sys.argv[4]
real_open = anchored_fs.os.open
real_write = anchored_fs.os.write
real_fsync = anchored_fs.os.fsync
real_link = anchored_fs.os.link
real_unlink = anchored_fs.os.unlink
published = False

def patched_open(path, flags, *args, **kwargs):
    descriptor = real_open(path, flags, *args, **kwargs)
    if crash == "after_staging_create" and flags & os.O_EXCL:
        os._exit(91)
    return descriptor
def patched_write(descriptor, data):
    if crash == "mid_write":
        real_write(descriptor, data[:max(1, len(data)//2)])
        os._exit(91)
    return real_write(descriptor, data)
def patched_fsync(descriptor):
    current = os.fstat(descriptor)
    real_fsync(descriptor)
    if crash == "after_file_fsync" and stat.S_ISREG(current.st_mode):
        os._exit(91)
    if crash == "after_inbox_fsync" and published and stat.S_ISDIR(current.st_mode):
        os._exit(91)
def patched_link(*args, **kwargs):
    global published
    real_link(*args, **kwargs)
    published = True
    if crash == "after_link":
        os._exit(91)
def patched_unlink(path, *args, **kwargs):
    real_unlink(path, *args, **kwargs)
    if crash == "after_staging_unlink" and str(path).endswith(".part"):
        os._exit(91)

anchored_fs.os.open = patched_open
anchored_fs.os.write = patched_write
anchored_fs.os.fsync = patched_fsync
anchored_fs.os.link = patched_link
anchored_fs.os.unlink = patched_unlink
GrowthInbox.open_for_record(repository, repository, state).record(request)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(repository), str(state), str(request_path), crash_point],
        env=environment,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 91
    inbox_entries = list((state / "inbox").iterdir())
    assert bool(inbox_entries) is final_expected
    if inbox_entries:
        from evolution_harness.growth_store import GrowthInbox

        normalized = normalize_growth_assessment_request(repository, request)
        receipt = GrowthInbox.open_read_only(repository, state).receipt(growth_assessment_id(normalized))
        assert receipt["assessment"] == normalized
        assert receipt["status"] == "RECORDED"
