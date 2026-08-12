from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath


class PathBoundaryError(ValueError):
    pass


def safe_relative_path(value: str, *, label: str = "path") -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PathBoundaryError(f"unsafe {label}: {value}")
    return path


def resolve_within(root: Path, relative: str, *, must_exist: bool = False, label: str = "path") -> Path:
    base = Path(root).resolve()
    rel = safe_relative_path(relative, label=label)
    candidate = (base / Path(*rel.parts)).resolve(strict=must_exist)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise PathBoundaryError(f"{label} escapes root: {relative}") from exc
    return candidate


def resolve_without_symlinks(
    root: Path,
    relative: str,
    *,
    must_exist: bool = False,
    label: str = "path",
) -> Path:
    base = Path(root).resolve()
    rel = safe_relative_path(relative, label=label)
    current = base
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise PathBoundaryError(f"{label} contains symlink: {relative}")
    if must_exist and not current.exists():
        raise FileNotFoundError(current)
    return current


def matches_excluded(relative: str, patterns: list[str]) -> bool:
    value = safe_relative_path(relative, label="source path").as_posix()
    return any(fnmatch.fnmatchcase(value, pattern) or PurePosixPath(value).match(pattern) for pattern in patterns)
