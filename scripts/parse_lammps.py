from __future__ import annotations
from pathlib import Path
from lammps_command import (
    Command, Completeness, IssueSeverity, LifecycleKind, LifecycleRecord,
    ParseIssue, ParseResult, SourceSpan,
    to_legacy_commands,  # noqa: F401  re-exported for the validate_input adapter
    active_lifecycle,    # noqa: F401  re-exported for downstream phases
)

DYNAMIC_FLOW = frozenset({"if", "jump", "label", "loop", "next"})


def _strip_comment(line: str) -> str:
    result = []
    in_quote = None
    for ch in line:
        if in_quote:
            result.append(ch)
            if ch == in_quote:
                in_quote = None
        elif ch == "#":
            break
        elif ch in ("\"", "'"):
            in_quote = ch
            result.append(ch)
        else:
            result.append(ch)
    return "".join(result)


def _merge_continuation(physical_lines):
    result = []
    pending = ""
    start = None
    for i, raw in enumerate(physical_lines, start=1):
        content = _strip_comment(raw)
        if start is None:
            start = i
        stripped = content.rstrip()
        if stripped.endswith("&"):
            pending += stripped[:-1]
        else:
            pending += stripped
            text = pending.strip()
            if text:
                result.append((text, start, i))
            pending = ""
            start = None
    if start is not None:
        text = pending.strip()
        if text:
            result.append((text, start, len(physical_lines)))
    return result


def _tokenize(text: str) -> list[str]:
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if text[i] in ("\"", "'"):
            quote = text[i]
            i += 1
            start = i
            while i < n and text[i] != quote:
                i += 1
            if i >= n:
                raise ValueError(f"unclosed {quote} quote in: {text}")
            tokens.append(text[start:i])
            i += 1
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in ("\"", "'"):
                i += 1
            tokens.append(text[start:i])
    return tokens


def _track_lifecycle(name, args, span, active):
    issues = []
    if name in ("fix", "compute", "dump") and len(args) >= 2:
        kind = LifecycleKind(name)
        identifier = args[0]
        group = args[1]
        style = args[2] if len(args) >= 3 else ""
        existing = active.get((kind, identifier))
        if existing and existing[-1].destroyed_at is None:
            issues.append(ParseIssue(
                IssueSeverity.WARNING, "LAMMPS_DUPLICATE_LIFECYCLE_ID",
                f"{kind.value} ID '{identifier}' created again without prior destruction", span))
        active.setdefault((kind, identifier), []).append(
            LifecycleRecord(kind, identifier, group, style, span, None))
    elif name in ("unfix", "uncompute", "undump") and args:
        kind = LifecycleKind(name[2:])
        identifier = args[0]
        records = active.get((kind, identifier))
        if not records or records[-1].destroyed_at is not None:
            issues.append(ParseIssue(
                IssueSeverity.WARNING, f"LAMMPS_{name.upper()}_UNKNOWN",
                f"{name} ID '{identifier}' has no active {kind.value} record", span))
        else:
            last = records[-1]
            records[-1] = LifecycleRecord(
                last.kind, last.identifier, last.group, last.style,
                last.created_at, span)
    return issues


def parse_lammps_file(path, *, allowed_root=None, max_depth=8) -> ParseResult:
    root = Path(path).resolve()
    root_text = root.read_text(encoding="utf-8", errors="replace")
    allowed = Path(allowed_root).resolve() if allowed_root else root.parent
    commands = []
    issues = []
    includes = []
    active = {}
    completeness = _parse_source(
        str(root), root_text, 0, frozenset({str(root)}),
        allowed, max_depth, commands, issues, includes, active)
    lifecycle = []
    for records in active.values():
        lifecycle.extend(records)
    return ParseResult(
        commands=tuple(commands), raw_text=root_text,
        issues=tuple(issues), completeness=completeness,
        lifecycle=tuple(lifecycle), includes=tuple(includes))


def _parse_source(source, text, depth, chain, allowed, max_depth,
                  commands, issues, includes, active):
    physical = text.splitlines()
    completeness = Completeness.COMPLETE
    for log_text, start, end in _merge_continuation(physical):
        span = SourceSpan(source, start, end)
        try:
            tokens = _tokenize(log_text)
        except ValueError as exc:
            issues.append(ParseIssue(
                IssueSeverity.ERROR, "LAMMPS_UNCLOSED_QUOTE", str(exc), span))
            completeness = Completeness.INCOMPLETE
            continue
        if not tokens:
            continue
        name = tokens[0].lower()
        args = tuple(tokens[1:])
        if name == "include" and args:
            sub = _handle_include(
                args[0], source, span, depth, chain, allowed, max_depth,
                commands, issues, includes, active)
            if sub == Completeness.INCOMPLETE:
                completeness = Completeness.INCOMPLETE
            continue
        commands.append(Command(name, args, span, log_text))
        if name in DYNAMIC_FLOW:
            issues.append(ParseIssue(
                IssueSeverity.WARNING, "LAMMPS_DYNAMIC_CONTROL_FLOW",
                f"dynamic control flow command '{name}' cannot be statically expanded", span))
            completeness = Completeness.INCOMPLETE
        issues.extend(_track_lifecycle(name, args, span, active))
    return completeness

def _handle_include(path_arg, source, span, depth, chain, allowed, max_depth,
                    commands, issues, includes, active):
    raw_path = path_arg.strip().strip("'\"")
    current_dir = Path(source).parent
    candidate = Path(raw_path) if Path(raw_path).is_absolute() else current_dir / raw_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError:
        issues.append(ParseIssue(
            IssueSeverity.ERROR, "LAMMPS_INCLUDE_ESCAPE",
            f"include path '{raw_path}' escapes allowed root '{allowed}'", span))
        return Completeness.INCOMPLETE
    resolved_str = str(resolved)
    if resolved_str in chain:
        issues.append(ParseIssue(
            IssueSeverity.ERROR, "LAMMPS_INCLUDE_CYCLE",
            f"include cycle detected: '{resolved_str}' is already in the include chain", span))
        return Completeness.INCOMPLETE
    if depth >= max_depth:
        issues.append(ParseIssue(
            IssueSeverity.ERROR, "LAMMPS_INCLUDE_DEPTH",
            f"include depth limit ({max_depth}) exceeded at '{resolved_str}'", span))
        return Completeness.INCOMPLETE
    if not resolved.exists():
        issues.append(ParseIssue(
            IssueSeverity.ERROR, "LAMMPS_INCLUDE_MISSING",
            f"included file not found: '{resolved_str}'", span))
        return Completeness.INCOMPLETE
    sub_text = resolved.read_text(encoding="utf-8", errors="replace")
    includes.append(resolved_str)
    new_chain = chain | {resolved_str}
    return _parse_source(
        resolved_str, sub_text, depth + 1, new_chain, allowed, max_depth,
        commands, issues, includes, active)
