from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from .assurance import structural_validate
from .capability_pack_registry import CapabilityVerificationSession
from .catalog import build_all_catalogs
from .controlled_coordinator import (
    acquire_lane_lease,
    inspect_project_coordinator,
    transition_lane_lease,
)
from .controlled_coordinator_inputs import ControlledCoordinationError
from .controlled_inputs import load_planning_request
from .controlled_planner import build_provisional_execution_plan
from .controlled_recovery import observe_lane_writes, record_project_recovery
from .discussion import materialize_discussion_contract, route_next_topics
from .evals import record_eval_result
from .feedback import capture_feedback_as_experience
from .handoff import build_design_handoff
from .growth_assessment import (
    GrowthAssessmentError,
    build_growth_capture_result,
    growth_assessment_id,
    growth_assessment_key,
    growth_request_digest,
    normalize_growth_assessment_request,
)
from .growth_source import validate_growth_source
from .growth_store import GrowthInbox
from .install import install_projection, uninstall_projection
from .integration import (
    build_integration_projection,
    check_integration_projection,
    load_integration,
    resolve_integration_context,
)
from .learning import create_candidate, promote_candidate, triage_experience, capture_experience
from .project import build_capability_lock, load_capability_lock
from .projection import build_projection_pack, check_projection_freshness
from .registration import check_project_registration, registered_integration_operation
from .registry import build_all_registries, build_design_registry
from .resolver import resolve_design_context
from .revalidation import check_revalidation
from .scenario import run_integration_scenario
from .toolchain_provisioning import (
    plan_toolchain_provision,
    provision_toolchain,
    toolchain_status,
)


def _load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


_GROWTH_REQUEST_LIMIT = 65_536
_GROWTH_ASSESSMENT_ID = re.compile(r"^growth-assessment:[0-9a-f]{24}$")


class _StrictGrowthLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.composer.ComposerError(
                None, None, "aliases are not permitted", self.peek_event().start_mark
            )
        event = self.peek_event()
        if getattr(event, "anchor", None) is not None:
            raise yaml.composer.ComposerError(
                None, None, "anchors are not permitted", event.start_mark
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None, "mapping node is invalid", node.start_mark
            )
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if (
                key_node.tag == "tag:yaml.org,2002:merge"
                or isinstance(key_node, yaml.ScalarNode)
                and key_node.value == "<<"
            ):
                raise yaml.constructor.ConstructorError(
                    None, None, "merge keys are not permitted", key_node.start_mark
                )
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(
                    None, None, "mapping keys must be strings", key_node.start_mark
                )
            if key in result:
                raise yaml.constructor.ConstructorError(
                    None, None, "duplicate mapping key", key_node.start_mark
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _growth_input_error(message: str) -> GrowthAssessmentError:
    return GrowthAssessmentError("ASSESSMENT_SCHEMA_INVALID", message)


def _bounded_growth_file(path: str) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode):
            raise _growth_input_error("growth request input must be a regular file")
        if current.st_size > _GROWTH_REQUEST_LIMIT:
            raise _growth_input_error("growth request exceeds the encoded-size limit")
        raw = os.read(descriptor, _GROWTH_REQUEST_LIMIT + 1)
    except GrowthAssessmentError:
        raise
    except OSError as exc:
        raise _growth_input_error("growth request file is unavailable or unsafe") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > _GROWTH_REQUEST_LIMIT:
        raise _growth_input_error("growth request exceeds the encoded-size limit")
    return raw


def _bounded_growth_stdin() -> bytes:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is not None:
        raw = stream.read(_GROWTH_REQUEST_LIMIT + 1)
    else:
        try:
            raw = sys.stdin.read(_GROWTH_REQUEST_LIMIT + 1).encode("utf-8")
        except UnicodeError as exc:
            raise _growth_input_error("growth request is not valid UTF-8") from exc
    if len(raw) > _GROWTH_REQUEST_LIMIT:
        raise _growth_input_error("growth request exceeds the encoded-size limit")
    return raw


def _load_growth_request(path: str) -> dict[str, Any]:
    raw = _bounded_growth_stdin() if path == "-" else _bounded_growth_file(path)
    try:
        document = raw.decode("utf-8", "strict")
        value = yaml.load(document, Loader=_StrictGrowthLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _growth_input_error("growth request is not one strict UTF-8 JSON or YAML document") from exc
    if not isinstance(value, dict):
        raise _growth_input_error("growth request document root must be an object")
    return value


class _GrowthValueAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        marker = f"_growth_seen_{self.dest}"
        if getattr(namespace, marker, False):
            parser.error("repeated growth argument")
        setattr(namespace, marker, True)
        setattr(namespace, self.dest, values)


class _GrowthFlagAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        marker = f"_growth_seen_{self.dest}"
        if getattr(namespace, marker, False):
            parser.error("repeated growth argument")
        setattr(namespace, marker, True)
        setattr(namespace, self.dest, True)


def _absolute_growth_path(value: str) -> str:
    if not Path(value).is_absolute():
        raise argparse.ArgumentTypeError("growth paths must be absolute")
    return value


def _growth_request_path(value: str) -> str:
    if value != "-" and not Path(value).is_absolute():
        raise argparse.ArgumentTypeError("growth request path must be absolute or stdin")
    return value


def _growth_assessment_id(value: str) -> str:
    if _GROWTH_ASSESSMENT_ID.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("growth assessment ID is invalid")
    return value


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


class _HarnessArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        command = self.prog.removeprefix("harness ")
        growth_command = getattr(self, "_growth_error_command", None)
        if command == "growth" or command.startswith("growth "):
            growth_command = command
        if growth_command is not None:
            _emit(
                {
                    "code": "GROWTH_ARGUMENT_INVALID",
                    "message": "invalid growth command arguments",
                },
                fmt="json",
                ok=False,
                command=growth_command,
            )
            raise SystemExit(1)
        coordination_command = getattr(
            self, "_coordination_error_command", None
        )
        if command == "coordination" or command.startswith("coordination "):
            coordination_command = command
        if coordination_command is not None:
            _emit(
                {
                    "code": "COORDINATION_ARGUMENT_INVALID",
                    "message": "invalid coordination command arguments",
                    "data": {},
                },
                fmt="json",
                ok=False,
                command=coordination_command,
            )
            raise SystemExit(1)
        super().error(message)


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


def _add_integration_resolution_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--integration")
    parser.add_argument("--source", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage")
    parser.add_argument("--runtime", choices=["CHATGPT", "CODEX"], required=True)
    parser.add_argument("--reopen-signal")


def _add_coordination_mutation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True)
    parser.add_argument("--request", required=True)


def _parse_toolchain_bindings(values: list[str]) -> dict[str, Path]:
    bindings: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or not raw_path:
            raise ValueError("toolchain binding must use NAME=ABSOLUTE_PATH")
        if name in bindings:
            raise ValueError(f"duplicate toolchain binding: {name}")
        path = Path(raw_path)
        if not path.is_absolute():
            raise ValueError(f"toolchain binding path must be absolute: {name}")
        bindings[name] = path
    return bindings


def _coordination_command_from_argv(argv: list[str]) -> str | None:
    index = 0
    if index < len(argv) and argv[index] == "--repository-root":
        index += 2
    elif index < len(argv) and argv[index].startswith("--repository-root="):
        index += 1
    if index >= len(argv) or argv[index] != "coordination":
        return None
    index += 1
    if index < len(argv) and argv[index] in {
        "status",
        "acquire",
        "transition",
        "observe",
        "recover",
    }:
        return f"coordination {argv[index]}"
    return "coordination"


def _growth_command_from_argv(argv: list[str]) -> str | None:
    index = 0
    if index < len(argv) and argv[index] == "--repository-root":
        index += 2
    elif index < len(argv) and argv[index].startswith("--repository-root="):
        index += 1
    if index >= len(argv) or argv[index] != "growth":
        return None
    index += 1
    if index < len(argv) and argv[index] in {"assess", "receipt", "scan"}:
        return f"growth {argv[index]}"
    return "growth"


def _emit_coordination(
    data: dict[str, Any], *, message: str, command: str
) -> int:
    return _emit(
        {"code": "OK", "message": message, "data": data},
        fmt="json",
        command=command,
    )


def _resolve(
    root: Path,
    args,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
    return resolve_design_context(
        root, Path(args.project), intent=args.intent, topic=args.topic, requested_output=args.output,
        runtime=args.runtime, explicit_stage=args.stage, reopen_signal=args.reopen_signal,
        verification_session=verification_session,
    )


@contextmanager
def _project_verification_operation(
    repository_root: Path,
    project_root: Path,
) -> Iterator[CapabilityVerificationSession]:
    root = Path(repository_root).resolve()
    project = Path(project_root)
    lock = load_capability_lock(root, project)
    external_ids = {
        item["capabilityId"]
        for item in lock["capabilities"]
        if item.get("sourceKind") == "EXTERNAL_CAPABILITY_PACK"
    }
    with CapabilityVerificationSession(
        root,
        allowed_capability_ids=external_ids,
    ) as verification_session:
        yield verification_session


def _growth_state_root(args) -> Path | None:
    value = getattr(args, "state_root", None)
    return None if value is None else Path(value)


def _preflight_growth_default_state_root(args) -> None:
    if getattr(args, "state_root", None) is not None:
        return
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and not Path(codex_home).is_absolute():
        raise GrowthAssessmentError("STATE_ROOT_UNSAFE", "CODEX_HOME must be absolute")


def _close_growth_inbox(inbox: GrowthInbox) -> None:
    inbox._close()


def _growth_assess(root: Path, args) -> dict[str, Any]:
    _preflight_growth_default_state_root(args)
    request = _load_growth_request(args.request)
    normalized = normalize_growth_assessment_request(root, request)
    source = Path(args.source)
    validate_growth_source(root, source, normalized)

    growth_assessment_key(normalized)
    growth_assessment_id(normalized)
    growth_request_digest(normalized)
    if args.state_root is None and not os.environ.get("CODEX_HOME"):
        return build_growth_capture_result(
            normalized, deferred_reason="STATE_ROOT_UNAVAILABLE"
        )

    inbox: GrowthInbox | None = None
    try:
        inbox = GrowthInbox.open_for_record(root, source, _growth_state_root(args))
        receipt = inbox.record(normalized)
    except GrowthAssessmentError as exc:
        if exc.code in {"STATE_ROOT_UNAVAILABLE", "INBOX_LOCKED"}:
            return build_growth_capture_result(normalized, deferred_reason=exc.code)
        raise
    finally:
        if inbox is not None:
            _close_growth_inbox(inbox)
    return build_growth_capture_result(normalized, receipt=receipt)


def _growth_receipt(root: Path, args) -> dict[str, Any]:
    _preflight_growth_default_state_root(args)
    inbox = GrowthInbox.open_read_only(root, _growth_state_root(args))
    try:
        return inbox.receipt(args.id)
    finally:
        _close_growth_inbox(inbox)


def _growth_scan(root: Path, args) -> dict[str, Any]:
    _preflight_growth_default_state_root(args)
    inbox = GrowthInbox.open_read_only(root, _growth_state_root(args))
    try:
        return inbox.scan(as_of=args.as_of)
    finally:
        _close_growth_inbox(inbox)


_GROWTH_PUBLIC_MESSAGES = {
    "ASSESSMENT_SCHEMA_INVALID": "growth assessment request is invalid",
    "GROWTH_ARGUMENT_INVALID": "growth request value is invalid",
    "ASSESSMENT_KEY_CONFLICT": "assessment key already has another receipt",
    "ASSESSMENT_ID_MISMATCH": "growth assessment identity does not match",
    "REQUEST_DIGEST_MISMATCH": "growth request digest does not match",
    "SOURCE_REGISTRATION_INVALID": "growth source registration is invalid",
    "SOURCE_CONTEXT_MISMATCH": "growth source context does not match",
    "SOURCE_AUTHORITY_NO_GO": "growth source authority is not acceptable",
    "SOURCE_REVISION_MISMATCH": "growth source revision does not match",
    "SOURCE_LOCK_MISMATCH": "growth source lock does not match",
    "SOURCE_SELF_INVALID": "Harness-self source context is invalid",
    "STATE_ROOT_UNAVAILABLE": "Growth Inbox state is unavailable",
    "STATE_ROOT_UNSAFE": "Growth Inbox state is unsafe",
    "INBOX_LOCKED": "Growth Inbox lock is busy",
    "RECEIPT_UNSAFE": "growth receipt is unsafe",
    "RECEIPT_CORRUPT": "growth receipt is corrupt",
    "RECEIPT_NOT_FOUND": "growth receipt was not found",
    "SCAN_LIMIT_EXCEEDED": "Growth Inbox scan limit was exceeded",
    "TIMESTAMP_INVALID": "growth timestamp is invalid",
}


def _growth_public_error(exc: Exception, *, action: str) -> dict[str, Any]:
    code = exc.code if isinstance(exc, GrowthAssessmentError) else "INTERNAL_ERROR"
    error = {
        "code": code,
        "message": _GROWTH_PUBLIC_MESSAGES.get(code, "growth command failed safely"),
    }
    if action == "assess":
        error["growthCaptureGate"] = "FAIL"
    return error


def build_parser(
    *,
    coordination_error_command: str | None = None,
    growth_error_command: str | None = None,
) -> argparse.ArgumentParser:
    parser = _HarnessArgumentParser(prog="harness")
    parser._coordination_error_command = coordination_error_command
    parser._growth_error_command = growth_error_command
    parser.add_argument("--repository-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate"); p.add_argument("--check-generated", action="store_true"); p.add_argument("--project", action="append"); p.add_argument("--scope", choices=("all", "core", "adoption"), default="all"); _add_format(p)
    p = sub.add_parser("list"); p.add_argument("--kind"); _add_format(p)
    p = sub.add_parser("show"); p.add_argument("id"); p.add_argument("--version"); _add_format(p)

    p = sub.add_parser("toolchain"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("status"); q.add_argument("--profile", required=True); _add_format(q)
    q = s.add_parser("provision"); q.add_argument("--profile", required=True); q.add_argument("--archive"); q.add_argument("--bind", action="append", default=[]); q.add_argument("--apply", action="store_true"); _add_format(q)

    p = sub.add_parser("registry"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("build"); q.add_argument("--check", action="store_true"); _add_format(q)
    p = sub.add_parser("catalog"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("build"); q.add_argument("--check", action="store_true"); _add_format(q)

    p = sub.add_parser("resolve"); _add_resolution_args(p); p.add_argument("--explain", action="store_true"); _add_format(p)

    p = sub.add_parser("planning"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("plan"); q.add_argument("--request", required=True); _add_format(q)

    p = sub.add_parser("growth", allow_abbrev=False)
    s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("assess", allow_abbrev=False)
    q.add_argument("--source", required=True, type=_absolute_growth_path, action=_GrowthValueAction)
    q.add_argument("--request", required=True, type=_growth_request_path, action=_GrowthValueAction)
    q.add_argument("--state-root", type=_absolute_growth_path, action=_GrowthValueAction)
    q.add_argument("--format", required=True, choices=("json",), action=_GrowthValueAction)
    q = s.add_parser("receipt", allow_abbrev=False)
    q.add_argument("--id", required=True, type=_growth_assessment_id, action=_GrowthValueAction)
    q.add_argument("--state-root", type=_absolute_growth_path, action=_GrowthValueAction)
    q.add_argument("--check", required=True, action=_GrowthFlagAction, default=False)
    q.add_argument("--format", required=True, choices=("json",), action=_GrowthValueAction)
    q = s.add_parser("scan", allow_abbrev=False)
    q.add_argument("--as-of", required=True, action=_GrowthValueAction)
    q.add_argument("--state-root", type=_absolute_growth_path, action=_GrowthValueAction)
    q.add_argument("--format", required=True, choices=("json",), action=_GrowthValueAction)

    p = sub.add_parser("coordination"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("status"); q.add_argument("--source", required=True)
    for action in ("acquire", "transition", "observe", "recover"):
        _add_coordination_mutation_args(s.add_parser(action))

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

    p = sub.add_parser("projection"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("build"); _add_resolution_args(q); q.add_argument("--check", action="store_true"); _add_format(q)
    q = s.add_parser("install"); q.add_argument("--pack", required=True); q.add_argument("--source"); q.add_argument("--target", required=True); q.add_argument("--apply", action="store_true"); _add_format(q)
    q = s.add_parser("uninstall"); q.add_argument("--target", required=True); q.add_argument("--apply", action="store_true"); _add_format(q)

    p = sub.add_parser("integration"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("registration-check"); q.add_argument("--source", required=True); _add_format(q)
    q = s.add_parser("inspect"); q.add_argument("--integration"); q.add_argument("--source", required=True); _add_format(q)
    q = s.add_parser("lock"); q.add_argument("--integration", required=True); q.add_argument("--check", action="store_true"); _add_format(q)
    q = s.add_parser("resolve"); _add_integration_resolution_args(q); q.add_argument("--explain", action="store_true"); _add_format(q)
    q = s.add_parser("projection"); _add_integration_resolution_args(q); q.add_argument("--check", action="store_true"); _add_format(q)
    q = s.add_parser("scenario"); q.add_argument("--integration", required=True); q.add_argument("--source", required=True); q.add_argument("--scenario", required=True); _add_format(q)
    p = sub.add_parser("discussion"); s = p.add_subparsers(dest="action", required=True)
    q = s.add_parser("materialize"); _add_resolution_args(q); q.add_argument("--persist"); _add_format(q)
    q = s.add_parser("route-next"); q.add_argument("--project", required=True); q.add_argument("--current-topic", required=True); _add_format(q)

    p = sub.add_parser("handoff"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("build"); q.add_argument("--project", required=True); q.add_argument("--check", action="store_true"); _add_format(q)
    p = sub.add_parser("feedback"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("capture"); q.add_argument("--file", required=True); q.add_argument("--experience-id", required=True); _add_format(q)
    p = sub.add_parser("revalidation"); s = p.add_subparsers(dest="action", required=True); q = s.add_parser("check"); q.add_argument("--as-of", required=True); q.add_argument("--trigger", action="append", default=[]); _add_format(q)
    return parser


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(
        coordination_error_command=_coordination_command_from_argv(arguments),
        growth_error_command=_growth_command_from_argv(arguments),
    )
    args = parser.parse_args(arguments)
    root = Path(args.repository_root)
    fmt = getattr(args, "format", "text")
    if args.command == "coordination":
        fmt = "json"
    if args.command == "growth":
        fmt = "json"
    command = args.command if not hasattr(args, "action") or args.action is None else f"{args.command} {args.action}"
    try:
        if args.command == "growth" and args.action == "assess":
            data = _growth_assess(root, args)
            return _emit(
                data,
                fmt="json",
                ok=data["growthCaptureGate"] == "PASS",
                command=command,
            )
        if args.command == "growth" and args.action == "receipt":
            return _emit(
                _growth_receipt(root, args),
                fmt="json",
                command=command,
            )
        if args.command == "growth" and args.action == "scan":
            data = _growth_scan(root, args)
            return _emit(
                data,
                fmt="json",
                ok=data["gate"] == "PASS",
                command=command,
            )
        if args.command == "validate":
            if args.scope == "core" and args.project:
                parser.error("validate --scope core does not accept --project")
            projects = [Path(p) for p in (args.project or [])]
            if (
                args.scope in {"all", "adoption"}
                and not projects
                and (root / "examples/project-fixture").exists()
            ):
                projects = [root / "examples/project-fixture"] if args.check_generated else []
            data = structural_validate(
                root,
                project_roots=projects,
                check_generated=args.check_generated,
                scope=args.scope,
            )
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
        if args.command == "toolchain" and args.action == "status":
            return _emit(
                toolchain_status(root, args.profile), fmt=fmt, command=command
            )
        if args.command == "toolchain" and args.action == "provision":
            bindings = _parse_toolchain_bindings(args.bind)
            archive = Path(args.archive) if args.archive is not None else None
            data = (
                provision_toolchain(root, args.profile, bindings, archive)
                if args.apply
                else plan_toolchain_provision(root, args.profile, bindings, archive)
            )
            return _emit(data, fmt=fmt, command=command)
        if args.command == "registry":
            expected = build_all_registries(root, write=not args.check)
            ok = True
            if args.check:
                paths = {
                    "design": root / "generated/registries/design-registry.json",
                    "designLearning": root / "generated/registries/design-learning-registry.json",
                    "engineering": root / "engineering/generated/registry.json",
                    "capabilityPacks": root
                    / "generated/registries/capability-pack-registry.json",
                }
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
        if args.command == "planning" and args.action == "plan":
            request = load_planning_request(root, Path(args.request))
            return _emit(
                build_provisional_execution_plan(root, request), fmt=fmt, command=command
            )
        if args.command == "coordination":
            source = Path(args.source)
            if args.action == "status":
                return _emit_coordination(
                    inspect_project_coordinator(root, source),
                    message="coordinator safety status inspected",
                    command=command,
                )
            request = _load_yaml(args.request)
            operations = {
                "acquire": (
                    acquire_lane_lease,
                    "coordinator lane lease acquired",
                ),
                "transition": (
                    transition_lane_lease,
                    "coordinator lane lease transitioned",
                ),
                "observe": (
                    observe_lane_writes,
                    "coordinator writes observed",
                ),
                "recover": (
                    record_project_recovery,
                    "coordinator recovery recorded",
                ),
            }
            operation, message = operations[args.action]
            return _emit_coordination(
                operation(root, source, request),
                message=message,
                command=command,
            )
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
        if args.command == "projection" and args.action == "build":
            with _project_verification_operation(
                root,
                Path(args.project),
            ) as verification_session:
                resolved = _resolve(
                    root,
                    args,
                    verification_session=verification_session,
                )
                if args.check:
                    check = check_projection_freshness(
                        root,
                        Path(args.project),
                        runtime=args.runtime,
                        expected_resolution_id=resolved["resolutionId"],
                        verification_session=verification_session,
                    )
                    return _emit({"fresh": check.fresh, "reasons": check.reasons}, fmt=fmt, ok=check.fresh, command=command)
                return _emit(
                    build_projection_pack(
                        root,
                        Path(args.project),
                        resolved,
                        runtime=args.runtime,
                        verification_session=verification_session,
                    ),
                    fmt=fmt,
                    command=command,
                )
        if args.command == "projection" and args.action == "install":
            data = install_projection(
                root,
                Path(args.pack),
                Path(args.target),
                source_root=Path(args.source) if args.source else None,
                apply=args.apply,
            )
            return _emit(data, fmt=fmt, ok=data["gate"] == "PASS", command=command)
        if args.command == "projection" and args.action == "uninstall":
            data = uninstall_projection(root, Path(args.target), apply=args.apply)
            return _emit(data, fmt=fmt, ok=data["gate"] == "PASS", command=command)
        if args.command == "integration" and args.action == "registration-check":
            data = check_project_registration(root, Path(args.source))
            return _emit(data, fmt=fmt, ok=data["gate"] == "PASS", command=command)
        if args.command == "integration" and args.action == "inspect":
            from .authority import build_authority_snapshot

            with registered_integration_operation(
                root,
                Path(args.source),
                Path(args.integration) if args.integration else None,
            ) as (loaded, _):
                data = build_authority_snapshot(
                    root,
                    loaded["integrationRoot"],
                    Path(args.source),
                )
                return _emit(data, fmt=fmt, ok=data["gate"] == "PASS", command=command)
        if args.command == "integration" and args.action == "lock":
            loaded = load_integration(root, Path(args.integration))
            expected = build_capability_lock(root, loaded["controlPlaneRoot"], write=not args.check)
            path = loaded["controlPlaneRoot"] / ".agent-evolution/capabilities.lock.yaml"
            ok = not args.check or (path.exists() and _load_yaml(path) == expected)
            return _emit(expected, fmt=fmt, ok=ok, command=command)
        if args.command == "integration" and args.action == "resolve":
            with registered_integration_operation(
                root,
                Path(args.source),
                Path(args.integration) if args.integration else None,
            ) as (loaded, verification_session):
                data = resolve_integration_context(
                    root,
                    loaded["integrationRoot"],
                    Path(args.source),
                    intent=args.intent,
                    topic=args.topic,
                    requested_output=args.output,
                    runtime=args.runtime,
                    explicit_stage=args.stage,
                    reopen_signal=args.reopen_signal,
                    verification_session=verification_session,
                )
                if not args.explain:
                    data = dict(data); data.pop("explain", None)
                return _emit(data, fmt=fmt, command=command)
        if args.command == "integration" and args.action == "projection":
            with registered_integration_operation(
                root,
                Path(args.source),
                Path(args.integration) if args.integration else None,
            ) as (loaded, verification_session):
                if args.check:
                    check = check_integration_projection(
                        root,
                        loaded["integrationRoot"],
                        Path(args.source),
                        runtime=args.runtime,
                        intent=args.intent,
                        topic=args.topic,
                        requested_output=args.output,
                        explicit_stage=args.stage,
                        reopen_signal=args.reopen_signal,
                        verification_session=verification_session,
                    )
                    return _emit({"fresh": check.fresh, "reasons": check.reasons}, fmt=fmt, ok=check.fresh, command=command)
                data = build_integration_projection(
                    root,
                    loaded["integrationRoot"],
                    Path(args.source),
                    intent=args.intent,
                    topic=args.topic,
                    requested_output=args.output,
                    runtime=args.runtime,
                    explicit_stage=args.stage,
                    reopen_signal=args.reopen_signal,
                    verification_session=verification_session,
                )
                return _emit(data, fmt=fmt, command=command)
        if args.command == "integration" and args.action == "scenario":
            data = run_integration_scenario(
                root, Path(args.integration), Path(args.source), Path(args.scenario)
            )
            return _emit(data, fmt=fmt, ok=data["gate"] == "PASS", command=command)
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
        if args.command == "growth":
            error = _growth_public_error(exc, action=args.action)
            fmt = "json"
        elif args.command == "coordination":
            if isinstance(exc, ControlledCoordinationError):
                code = exc.code
                message = str(exc)
            elif isinstance(exc, OSError):
                code = "SYSTEM_ERROR"
                message = "coordination system operation failed"
            else:
                code = "INTERNAL_ERROR"
                message = "coordination internal failure"
            error = {"code": code, "message": message, "data": {}}
        else:
            code = getattr(exc, "code", "INTERNAL_ERROR")
            error = {"code": code, "message": str(exc)}
        return _emit(error, fmt=fmt, ok=False, command=command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
