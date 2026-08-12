from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from .assurance import structural_validate
from .catalog import build_all_catalogs
from .discussion import materialize_discussion_contract, route_next_topics
from .evals import record_eval_result
from .feedback import capture_feedback_as_experience
from .handoff import build_design_handoff
from .learning import create_candidate, promote_candidate, triage_experience, capture_experience
from .project import build_capability_lock
from .projection import build_projection_pack, check_projection_freshness
from .registry import build_all_registries, build_design_registry
from .resolver import resolve_design_context
from .revalidation import check_revalidation


def _load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _emit(data: Any, *, fmt: str, ok: bool = True, command: str = "") -> int:
    payload = {"schemaVersion": "harness-cli/v1", "ok": ok, "command": command, "data": data}
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        if isinstance(data, str):
            print(data)
        else:
            print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip())
    return 0 if ok else 1


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=["text", "json"], default="text")


def _add_resolution_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage")
    parser.add_argument("--runtime", choices=["CHATGPT", "CODEX", "GENERIC_AGENT"], required=True)
    parser.add_argument("--reopen-signal")


def _resolve(root: Path, args) -> dict[str, Any]:
    return resolve_design_context(
        root, Path(args.project), intent=args.intent, topic=args.topic, requested_output=args.output,
        runtime=args.runtime, explicit_stage=args.stage, reopen_signal=args.reopen_signal,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness")
    parser.add_argument("--repository-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate"); p.add_argument("--check-generated", action="store_true"); p.add_argument("--project", action="append"); _add_format(p)
    p = sub.add_parser("list"); p.add_argument("--kind"); _add_format(p)
    p = sub.add_parser("show"); p.add_argument("id"); p.add_argument("--version"); _add_format(p)

    p = sub.add_parser("registry"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("build"); q.add_argument("--check", action="store_true"); _add_format(q)
    p = sub.add_parser("catalog"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("build"); q.add_argument("--check", action="store_true"); _add_format(q)

    p = sub.add_parser("resolve"); _add_resolution_args(p); p.add_argument("--explain", action="store_true"); _add_format(p)

    p = sub.add_parser("project"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("lock"); q.add_argument("--project", required=True); q.add_argument("--check", action="store_true"); _add_format(q)
    q = s.add_parser("bind"); q.add_argument("--project", required=True); q.add_argument("--profile", action="append"); q.add_argument("--capability", action="append"); q.add_argument("--extension", action="append"); q.add_argument("--disable", action="append"); _add_format(q)

    p = sub.add_parser("experience"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("capture"); q.add_argument("--file", required=True); _add_format(q)
    q = s.add_parser("triage"); q.add_argument("--id", required=True); q.add_argument("--decision", required=True); _add_format(q)

    p = sub.add_parser("candidate"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("create"); q.add_argument("--candidate", required=True); q.add_argument("--asset", required=True); q.add_argument("--content", required=True); _add_format(q)
    q = s.add_parser("promote"); q.add_argument("--id", required=True); q.add_argument("--apply", action="store_true"); _add_format(q)

    p = sub.add_parser("eval"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("run"); q.add_argument("--result", required=True); _add_format(q)

    p = sub.add_parser("projection"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("build"); _add_resolution_args(q); q.add_argument("--check", action="store_true"); _add_format(q)
    p = sub.add_parser("discussion"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("materialize"); _add_resolution_args(q); q.add_argument("--persist"); _add_format(q)
    q = s.add_parser("route-next"); q.add_argument("--project", required=True); q.add_argument("--current-topic", required=True); _add_format(q)

    p = sub.add_parser("handoff"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("build"); q.add_argument("--project", required=True); q.add_argument("--check", action="store_true"); _add_format(q)
    p = sub.add_parser("feedback"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("capture"); q.add_argument("--file", required=True); q.add_argument("--experience-id", required=True); _add_format(q)
    p = sub.add_parser("revalidation"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("check"); q.add_argument("--as-of", required=True); q.add_argument("--trigger", action="append", default=[]); _add_format(q)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.repository_root)
    fmt = getattr(args, "format", "text")
    command = args.command if not hasattr(args, "action") or args.action is None else f"{args.command} {args.action}"
    try:
        if args.command == "validate":
            projects = [Path(p) for p in (args.project or [])]
            if not projects and (root / "examples/project-fixture").exists():
                projects = [root / "examples/project-fixture"] if args.check_generated else []
            data = structural_validate(root, project_roots=projects, check_generated=args.check_generated)
            return _emit(data, fmt=fmt, ok=data["structuralGate"] == "PASS", command=command)
        if args.command == "list":
            entries = build_design_registry(root, write=False)["entries"]
            if args.kind:
                entries = [entry for entry in entries if entry["kind"] == args.kind.upper()]
            return _emit(entries, fmt=fmt, command=command)
        if args.command == "show":
            entries = [entry for entry in build_design_registry(root, write=False)["entries"] if entry["id"] == args.id and (not args.version or entry["version"] == args.version)]
            if not entries:
                return _emit({"code": "NOT_FOUND", "message": args.id}, fmt=fmt, ok=False, command=command)
            return _emit(entries[-1], fmt=fmt, command=command)
        if args.command == "registry":
            expected = build_all_registries(root, write=not args.check)
            ok = True
            if args.check:
                paths = {"design": root / "generated/registries/design-registry.json", "designLearning": root / "generated/registries/design-learning-registry.json", "engineering": root / "engineering/generated/registry.json"}
                ok = all(path.exists() and json.loads(path.read_text(encoding="utf-8")) == expected[key] for key, path in paths.items())
            counts = {key: len(value["entries"]) for key, value in expected.items()}
            return _emit({"check": args.check, "counts": counts}, fmt=fmt, ok=ok, command=command)
        if args.command == "catalog":
            expected = build_all_catalogs(root, write=not args.check)
            ok = True
            if args.check:
                paths = {"design": root / "generated/catalogs/design-active-catalog.json", "engineering": root / "engineering/generated/active-catalog.json", "unified": root / "generated/catalogs/unified-active-catalog.json"}
                ok = all(path.exists() and json.loads(path.read_text(encoding="utf-8")) == expected[key] for key, path in paths.items())
            return _emit({"check": args.check, "counts": {key: len(value["entries"]) for key, value in expected.items()}}, fmt=fmt, ok=ok, command=command)
        if args.command == "resolve":
            data = _resolve(root, args)
            if not args.explain:
                data = dict(data); data.pop("explain", None)
            return _emit(data, fmt=fmt, command=command)
        if args.command == "project" and args.action == "lock":
            expected = build_capability_lock(root, Path(args.project), write=not args.check)
            path = Path(args.project) / ".agent-evolution/capabilities.lock.yaml"
            ok = not args.check or (path.exists() and (_load_yaml(path) == expected))
            return _emit(expected, fmt=fmt, ok=ok, command=command)
        if args.command == "project" and args.action == "bind":
            path = Path(args.project) / ".agent-evolution/capabilities.yaml"
            current = _load_yaml(path) if path.exists() else {"schemaVersion": "project-capability-binding/v1", "profiles": [], "capabilities": [], "extensions": [], "disabledCapabilities": []}
            for field, values in [("profiles", args.profile), ("capabilities", args.capability), ("extensions", args.extension), ("disabledCapabilities", args.disable)]:
                if values:
                    current[field] = sorted(set(current.get(field, []) + values))
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(yaml.safe_dump(current, sort_keys=False), encoding="utf-8")
            return _emit(current, fmt=fmt, command=command)
        if args.command == "experience" and args.action == "capture":
            path = capture_experience(root, _load_yaml(args.file)); return _emit({"location": str(path)}, fmt=fmt, command=command)
        if args.command == "experience" and args.action == "triage":
            return _emit(triage_experience(root, args.id, args.decision), fmt=fmt, command=command)
        if args.command == "candidate" and args.action == "create":
            path = create_candidate(root, _load_yaml(args.candidate), _load_yaml(args.asset), Path(args.content).read_text(encoding="utf-8")); return _emit({"location": str(path)}, fmt=fmt, command=command)
        if args.command == "candidate" and args.action == "promote":
            return _emit(promote_candidate(root, args.id, apply=args.apply), fmt=fmt, command=command)
        if args.command == "eval":
            path = record_eval_result(root, _load_yaml(args.result)); return _emit({"location": str(path)}, fmt=fmt, command=command)
        if args.command == "projection":
            if args.check:
                check = check_projection_freshness(root, Path(args.project), runtime=args.runtime)
                return _emit({"fresh": check.fresh, "reasons": check.reasons}, fmt=fmt, ok=check.fresh, command=command)
            resolved = _resolve(root, args); return _emit(build_projection_pack(root, Path(args.project), resolved, runtime=args.runtime), fmt=fmt, command=command)
        if args.command == "discussion" and args.action == "materialize":
            resolved = _resolve(root, args); text = materialize_discussion_contract(root, Path(args.project), resolved, persist_path=Path(args.persist) if args.persist else None); return _emit(text, fmt=fmt, command=command)
        if args.command == "discussion" and args.action == "route-next":
            return _emit(route_next_topics(root, Path(args.project), current_topic=args.current_topic), fmt=fmt, command=command)
        if args.command == "handoff":
            expected = build_design_handoff(root, Path(args.project), write=not args.check)
            path = Path(args.project) / ".agent-evolution/design-handoff.yaml"
            ok = not args.check or (path.exists() and _load_yaml(path) == expected)
            return _emit(expected, fmt=fmt, ok=ok, command=command)
        if args.command == "feedback":
            path = capture_feedback_as_experience(root, _load_yaml(args.file), experience_id=args.experience_id); return _emit({"location": str(path)}, fmt=fmt, command=command)
        if args.command == "revalidation":
            return _emit(check_revalidation(root, as_of=args.as_of, triggers=args.trigger), fmt=fmt, command=command)
    except Exception as exc:
        code = getattr(exc, "code", "INTERNAL_ERROR")
        return _emit({"code": code, "message": str(exc)}, fmt=fmt, ok=False, command=command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
