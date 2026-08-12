from __future__ import annotations

from pathlib import Path


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
