from __future__ import annotations

import argparse
import json
from pathlib import Path

from evolution_harness.catalog import build_engineering_active_catalog
from evolution_harness.engineering_compat import engineering_doctor, resolve_engineering_context, validate_engineering
from evolution_harness.registry import build_engineering_registry


def _emit(data, ok=True):
    print(json.dumps({"schema_version": "engineering-cli/v1", "ok": ok, "data": data}, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["validate", "doctor", "test"]:
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
        if name == "doctor":
            p.add_argument("--ci", action="store_true")
    reg = sub.add_parser("registry")
    reg_sub = reg.add_subparsers(dest="action", required=True)
    rb = reg_sub.add_parser("build")
    rb.add_argument("--check", action="store_true")
    rb.add_argument("--json", action="store_true")
    cat = sub.add_parser("catalog")
    cat_sub = cat.add_subparsers(dest="action", required=True)
    cb = cat_sub.add_parser("build")
    cb.add_argument("--check", action="store_true")
    cb.add_argument("--json", action="store_true")
    context = sub.add_parser("context")
    context_sub = context.add_subparsers(dest="action", required=True)
    cr = context_sub.add_parser("resolve")
    cr.add_argument("--input")
    cr.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repository_root)
    try:
        if args.command == "validate":
            data = validate_engineering(root)
            return _emit(data, data["engineeringDomain"] == "PASS")
        if args.command == "doctor":
            data = engineering_doctor(root, ci=args.ci)
            return _emit(data, data["engineeringDomain"] == "PASS")
        if args.command == "registry":
            expected = build_engineering_registry(root, write=not args.check)
            path = root / "engineering/generated/registry.json"
            ok = not args.check or (path.exists() and json.loads(path.read_text(encoding="utf-8")) == expected)
            return _emit({"check": bool(args.check), "entryCount": len(expected["entries"])}, ok)
        if args.command == "catalog":
            expected = build_engineering_active_catalog(root, write=not args.check)
            path = root / "engineering/generated/active-catalog.json"
            ok = not args.check or (path.exists() and json.loads(path.read_text(encoding="utf-8")) == expected)
            return _emit({"check": bool(args.check), "entryCount": len(expected["entries"])}, ok)
        if args.command == "context":
            return _emit(resolve_engineering_context(root))
        if args.command == "test":
            data = engineering_doctor(root, ci=True)
            return _emit({"testGate": data["engineeringDomain"], "issues": data["issues"]}, data["engineeringDomain"] == "PASS")
    except Exception as exc:
        return _emit({"code": "INTERNAL_ERROR", "message": str(exc)}, False)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
