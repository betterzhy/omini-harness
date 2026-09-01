from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


def test_anchored_recursive_cleanup_unlinks_symlink_without_touching_referent(tmp_path: Path):
    from evolution_harness.anchored_fs import AnchoredRoot

    root = tmp_path / "root"
    managed = root / "managed"
    outside = tmp_path / "outside"
    managed.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")
    (managed / "outside-link").symlink_to(outside, target_is_directory=True)

    with AnchoredRoot(root) as filesystem:
        filesystem.remove_tree("managed")

    assert not managed.exists()
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"


def test_publish_bytes_no_replace_commits_complete_owner_only_inode_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from evolution_harness import anchored_fs

    root = tmp_path / "root"
    (root / "staging").mkdir(parents=True)
    (root / "inbox").mkdir()
    events: list[str] = []
    real_fsync = anchored_fs.os.fsync
    real_link = anchored_fs.os.link
    real_unlink = anchored_fs.os.unlink

    def observed_fsync(descriptor: int) -> None:
        current = os.fstat(descriptor)
        if stat.S_ISREG(current.st_mode):
            events.append("file-fsync")
        elif current.st_ino == (root / "inbox").stat().st_ino:
            events.append("inbox-fsync")
        elif current.st_ino == (root / "staging").stat().st_ino:
            events.append("staging-fsync")
        real_fsync(descriptor)

    def observed_link(*args, **kwargs) -> None:
        events.append("link")
        real_link(*args, **kwargs)

    def observed_unlink(path, *args, **kwargs) -> None:
        if str(path).endswith(".part"):
            events.append("staging-unlink")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(anchored_fs.os, "fsync", observed_fsync)
    monkeypatch.setattr(anchored_fs.os, "link", observed_link)
    monkeypatch.setattr(anchored_fs.os, "unlink", observed_unlink)

    with anchored_fs.AnchoredRoot(root) as filesystem:
        filesystem.publish_bytes_no_replace("staging", "inbox/receipt.json", b"complete\n")

    receipt = root / "inbox" / "receipt.json"
    assert receipt.read_bytes() == b"complete\n"
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert list((root / "staging").iterdir()) == []
    assert events.index("file-fsync") < events.index("link")
    assert events.index("link") < events.index("inbox-fsync")
    assert events.index("inbox-fsync") < events.index("staging-unlink")
    assert events.index("staging-unlink") < events.index("staging-fsync")


@pytest.mark.parametrize("target_kind", ["regular", "symlink", "directory", "fifo"])
def test_publish_bytes_no_replace_never_replaces_an_existing_target(tmp_path: Path, target_kind: str):
    from evolution_harness.anchored_fs import AnchoredPathError, AnchoredRoot

    root = tmp_path / "root"
    staging = root / "staging"
    inbox = root / "inbox"
    outside = tmp_path / "outside.txt"
    staging.mkdir(parents=True)
    inbox.mkdir()
    target = inbox / "receipt.json"
    if target_kind == "regular":
        target.write_bytes(b"winner\n")
    elif target_kind == "symlink":
        outside.write_bytes(b"referent\n")
        target.symlink_to(outside)
    elif target_kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target, 0o600)

    with AnchoredRoot(root) as filesystem:
        with pytest.raises(AnchoredPathError):
            filesystem.publish_bytes_no_replace("staging", "inbox/receipt.json", b"loser\n")

    current = target.lstat()
    expected_types = {
        "regular": stat.S_ISREG,
        "symlink": stat.S_ISLNK,
        "directory": stat.S_ISDIR,
        "fifo": stat.S_ISFIFO,
    }
    assert expected_types[target_kind](current.st_mode)
    if target_kind == "regular":
        assert target.read_bytes() == b"winner\n"
    if target_kind == "symlink":
        assert outside.read_bytes() == b"referent\n"


def test_publish_bytes_no_replace_rejects_symlink_directory_without_touching_referent(tmp_path: Path):
    from evolution_harness.anchored_fs import AnchoredPathError, AnchoredRoot

    root = tmp_path / "root"
    outside = tmp_path / "outside"
    (root / "staging").mkdir(parents=True)
    outside.mkdir()
    (root / "inbox").symlink_to(outside, target_is_directory=True)

    with AnchoredRoot(root) as filesystem:
        with pytest.raises(AnchoredPathError):
            filesystem.publish_bytes_no_replace("staging", "inbox/receipt.json", b"forbidden\n")

    assert list(outside.iterdir()) == []


def test_publish_bytes_no_replace_rejects_cross_device_directories(tmp_path: Path, monkeypatch):
    from evolution_harness import anchored_fs

    root = tmp_path / "root"
    (root / "staging").mkdir(parents=True)
    (root / "inbox").mkdir()
    real_fstat = anchored_fs.os.fstat
    inbox_inode = (root / "inbox").stat().st_ino

    def cross_device(descriptor: int):
        current = real_fstat(descriptor)
        if stat.S_ISDIR(current.st_mode) and current.st_ino == inbox_inode:
            values = list(current)
            values[2] = current.st_dev + 1
            return os.stat_result(values)
        return current

    monkeypatch.setattr(anchored_fs.os, "fstat", cross_device)
    with anchored_fs.AnchoredRoot(root) as filesystem:
        with pytest.raises(anchored_fs.AnchoredPathError, match="same device"):
            filesystem.publish_bytes_no_replace("staging", "inbox/receipt.json", b"forbidden\n")

    assert list((root / "inbox").iterdir()) == []


def test_two_real_process_publishers_preserve_exactly_one_complete_winner(tmp_path: Path):
    root = tmp_path / "root"
    (root / "staging").mkdir(parents=True)
    (root / "inbox").mkdir()
    repository = Path(__file__).parents[1]
    script = """
import sys
from pathlib import Path
from evolution_harness.anchored_fs import AnchoredPathError, AnchoredRoot
try:
    with AnchoredRoot(Path(sys.argv[1])) as filesystem:
        filesystem.publish_bytes_no_replace("staging", "inbox/receipt.json", sys.argv[2].encode())
except AnchoredPathError:
    raise SystemExit(23)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "src")
    processes = [
        subprocess.Popen([sys.executable, "-c", script, str(root), payload], env=environment)
        for payload in ("winner-a", "winner-b")
    ]
    returncodes = [process.wait(timeout=10) for process in processes]

    assert sorted(returncodes) == [0, 23]
    assert (root / "inbox" / "receipt.json").read_bytes() in {b"winner-a", b"winner-b"}


@pytest.mark.parametrize(
    ("crash_point", "may_have_final"),
    [
        ("after_staging_create", False),
        ("mid_write", False),
        ("after_file_fsync", False),
        ("after_link", True),
        ("after_inbox_fsync", True),
        ("after_staging_unlink", True),
    ],
)
def test_process_death_never_exposes_a_partial_published_inode(
    tmp_path: Path, crash_point: str, may_have_final: bool
):
    root = tmp_path / "root"
    (root / "staging").mkdir(parents=True)
    (root / "inbox").mkdir()
    repository = Path(__file__).parents[1]
    payload = (json.dumps({"receipt": "x" * 20000}, sort_keys=True) + "\n").encode()
    script = r"""
import os
import stat
import sys
from pathlib import Path
from evolution_harness import anchored_fs

root = Path(sys.argv[1])
crash = sys.argv[2]
payload = Path(sys.argv[3]).read_bytes()
real_open = anchored_fs.os.open
real_write = anchored_fs.os.write
real_fsync = anchored_fs.os.fsync
real_link = anchored_fs.os.link
real_unlink = anchored_fs.os.unlink
published = False
inbox_inode = (root / "inbox").stat().st_ino

def patched_open(path, flags, *args, **kwargs):
    descriptor = real_open(path, flags, *args, **kwargs)
    if crash == "after_staging_create" and flags & os.O_EXCL:
        os._exit(91)
    return descriptor

def patched_write(descriptor, data):
    if crash == "mid_write":
        real_write(descriptor, data[: max(1, len(data) // 2)])
        os._exit(91)
    return real_write(descriptor, data)

def patched_fsync(descriptor):
    current = os.fstat(descriptor)
    real_fsync(descriptor)
    if crash == "after_file_fsync" and stat.S_ISREG(current.st_mode):
        os._exit(91)
    if crash == "after_inbox_fsync" and published and current.st_ino == inbox_inode:
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
with anchored_fs.AnchoredRoot(root) as filesystem:
    filesystem.publish_bytes_no_replace("staging", "inbox/receipt.json", payload)
"""
    payload_path = tmp_path / "payload.json"
    payload_path.write_bytes(payload)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(root), crash_point, str(payload_path)],
        env=environment,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 91
    final = root / "inbox" / "receipt.json"
    if not may_have_final:
        assert not final.exists()
    elif final.exists():
        assert final.read_bytes() == payload
