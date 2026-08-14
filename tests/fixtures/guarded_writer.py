from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _write(path: str, payload: str = "guarded write\n") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")


def main(argv: list[str]) -> int:
    operation = argv[1]
    if operation == "write":
        _write(argv[2], argv[3] if len(argv) > 3 else "guarded write\n")
        return 0
    if operation == "write-remove":
        target = Path(argv[2])
        _write(str(target))
        target.unlink()
        target.parent.rmdir()
        return 0
    if operation == "mkdir":
        Path(argv[2]).mkdir(parents=True, exist_ok=True)
        return 0
    if operation == "symlink-write":
        link = Path(argv[2])
        link.symlink_to(Path(argv[3]), target_is_directory=True)
        _write(str(link / "escaped.txt"))
        return 0
    if operation == "signal-write":
        ready = Path(argv[3])
        _write(str(ready), "ready\n")
        time.sleep(float(argv[4]))
        ready.unlink(missing_ok=True)
        try:
            ready.parent.rmdir()
        except OSError:
            pass
        _write(argv[2])
        return 0
    if operation == "delayed-detached-write":
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "sleep-write",
                argv[2],
                argv[3],
            ],
            close_fds=True,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.write(1, f"{child.pid}\n".encode("ascii"))
        time.sleep(0.05)
        return 0
    if operation == "sleep-write":
        time.sleep(float(argv[3]))
        _write(argv[2])
        return 0
    raise SystemExit(f"unknown guarded writer operation: {operation}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
