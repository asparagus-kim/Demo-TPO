"""Auto-modify `app/services/ambience_service.py` with learned priors (and restore).

This is the *only* script that writes to the production `ambience_service.py`
source file. It is intentionally kept separate from the RL training code so
that a human has to run it explicitly — the training pipeline never promotes
params on its own.

Two operations:

    --from <learned.json>      Rewrite the prior tables (and optionally the
                               daypart windows) inside ambience_service.py
                               using the `effective` block of a learned-params
                               JSON produced by `export_params.export()`.
    --restore                  Revert every table to the values captured in
                               the baseline snapshot.

The first successful apply writes a snapshot of the *pre-change* prior tables
to ``outputs/rl_calibration/baseline_snapshot.json``. That snapshot is never
overwritten afterwards — subsequent applies will always compare to it and
subsequent restores will always reproduce it. If you want to reset the
snapshot (for example, after hand-editing the priors), delete the snapshot
file and run apply again.

Source-level edits are done via a robust AST-line-range splice — we find
the assignment node for each tracked symbol, then splice in a fresh
pretty-printed literal over its line range. Comments and surrounding code
outside those ranges are preserved byte-for-byte.

Usage
=====
    # Preview a proposed apply (no files touched):
    python -m app.research.rl_calibration.apply_to_production \\
        --from outputs/rl_calibration/learned_params/ambience_v1.json --dry-run

    # Apply it:
    python -m app.research.rl_calibration.apply_to_production \\
        --from outputs/rl_calibration/learned_params/ambience_v1.json

    # Revert to pristine production values:
    python -m app.research.rl_calibration.apply_to_production --restore
"""
from __future__ import annotations

import argparse
import ast
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...config import PROJECT_ROOT
from .config import OUTPUT_ROOT, ensure_output_dirs


def _safe_print(msg: str) -> None:
    """Print to stdout, degrading gracefully on non-UTF-8 consoles (e.g. CP949)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        import sys
        enc = getattr(sys.stdout, "encoding", "ascii") or "ascii"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


AMBIENCE_FILE: Path = PROJECT_ROOT / "app" / "services" / "ambience_service.py"
BASELINE_SNAPSHOT: Path = OUTPUT_ROOT / "baseline_snapshot.json"
BACKUP_DIR: Path = OUTPUT_ROOT / "apply_backups"

# Symbols this script knows how to rewrite. Order matters only for the
# report; edits are applied bottom-up so earlier line numbers stay valid.
_DICT_SYMBOLS: List[str] = [
    "TRADE_AREA_PRIORS",
    "BUSINESS_TYPE_PRIORS",
    "DAYPART_PRIORS",
    "WEATHER_PRIORS",
    "DEFAULT_TRADE",
    "DEFAULT_TYPE",
]
_LIST_SYMBOLS: List[str] = ["DAYPART_WINDOWS"]
_AXES: Tuple[str, str, str] = ("E", "T", "M")


# --------------------------------------------------------------- AST helpers
def _find_assignment_range(source: str, var_name: str) -> Tuple[int, int]:
    """Return (start_line, end_line) — 1-based, inclusive — for a top-level assignment.

    Handles both `x = {...}` and `x: T = {...}` forms. Raises ValueError if
    not found.
    """
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == var_name:
                    return node.lineno, node.end_lineno
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == var_name:
                return node.lineno, node.end_lineno
    raise ValueError(f"top-level assignment to {var_name!r} not found")


def _annotation_prefix(source: str, var_name: str) -> str:
    """Return the exact 'LHS = ' prefix of the assignment (including annotation).

    Used so we preserve the type-annotation, e.g.
    ``TRADE_AREA_PRIORS: Dict[str, Dict[str, float]] = {...}``.
    """
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == var_name:
                # Slice the source from start-of-assignment to just before the
                # value node's first column.
                lines = source.splitlines(keepends=True)
                start = sum(len(line) for line in lines[:node.lineno - 1]) + node.col_offset
                value = node.value
                value_start_line = value.lineno - 1
                value_start = (sum(len(line) for line in lines[:value_start_line])
                               + value.col_offset)
                return source[start:value_start]
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == var_name:
                    lines = source.splitlines(keepends=True)
                    start = sum(len(line) for line in lines[:node.lineno - 1]) + node.col_offset
                    value = node.value
                    value_start_line = value.lineno - 1
                    value_start = (sum(len(line) for line in lines[:value_start_line])
                                   + value.col_offset)
                    return source[start:value_start]
    raise ValueError(f"top-level assignment to {var_name!r} not found")


# --------------------------------------------------------------- literal formatters
def _fmt_float(v: float) -> str:
    # Match existing style: two decimals where possible, fall back to a
    # shorter repr that round-trips.
    if abs(v) < 1e-12:
        return "0.0"
    return f"{v:.2f}" if abs(round(v, 2) - v) < 1e-9 else repr(round(v, 4))


def _render_axis_dict(d: Dict[str, float]) -> str:
    parts = [f'"{a}": {_fmt_float(float(d[a]))}' for a in _AXES if a in d]
    return "{" + ", ".join(parts) + "}"


def _render_nested_priors(table: Dict[str, Dict[str, float]]) -> str:
    # Preserve insertion order of the input — callers pass in canonical order.
    # NOTE: kept backslash-free inside f-string expressions so this parses on
    # Python < 3.12 as well.
    if not table:
        return "{}"
    quoted = [f'"{k}"' for k in table]
    key_width = max(len(q) for q in quoted)
    inner_lines = []
    for q, (_k, v) in zip(quoted, table.items()):
        inner_lines.append(f"    {q:<{key_width}}: {_render_axis_dict(v)},")
    return "{\n" + "\n".join(inner_lines) + "\n}"


def _render_flat_priors(table: Dict[str, float]) -> str:
    parts = [f'"{a}": {_fmt_float(float(table[a]))}' for a in _AXES if a in table]
    return "{" + ", ".join(parts) + "}"


def _render_daypart_windows(windows: List[Tuple[str, int, int]]) -> str:
    lines = ["["]
    for name, s, e in windows:
        comment = "  # wraps past midnight" if e > 24 and name == "late_night" else ""
        lines.append(f'    ("{name}", {int(s)}, {int(e)}),{comment}')
    lines.append("]")
    return "\n".join(lines)


# --------------------------------------------------------------- read production
def _read_current_values() -> Dict[str, Any]:
    """Read the live prior tables from the ambience_service module.

    We import it fresh so the snapshot reflects whatever the file currently
    says on disk (not a cached import from earlier in this Python session).
    """
    import importlib
    from ...services import ambience_service as mod
    importlib.reload(mod)
    return {
        "TRADE_AREA_PRIORS": {k: dict(v) for k, v in mod.TRADE_AREA_PRIORS.items()},
        "BUSINESS_TYPE_PRIORS": {k: dict(v) for k, v in mod.BUSINESS_TYPE_PRIORS.items()},
        "DAYPART_PRIORS": {k: dict(v) for k, v in mod.DAYPART_PRIORS.items()},
        "WEATHER_PRIORS": {k: dict(v) for k, v in mod.WEATHER_PRIORS.items()},
        "DEFAULT_TRADE": dict(mod.DEFAULT_TRADE),
        "DEFAULT_TYPE": dict(mod.DEFAULT_TYPE),
        "DAYPART_WINDOWS": [list(t) for t in mod.DAYPART_WINDOWS],
    }


def _ensure_baseline_snapshot() -> Dict[str, Any]:
    """Return the baseline snapshot, creating it from the current module if absent.

    Once a snapshot exists it is treated as immutable — the restore target
    remains the originally-captured production state regardless of subsequent
    applies.
    """
    ensure_output_dirs()
    if BASELINE_SNAPSHOT.exists():
        return json.loads(BASELINE_SNAPSHOT.read_text(encoding="utf-8"))
    current = _read_current_values()
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(AMBIENCE_FILE),
        "values": current,
    }
    BASELINE_SNAPSHOT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


# --------------------------------------------------------------- rewrite core
def _splice_assignment(
    source: str,
    var_name: str,
    new_value_literal: str,
) -> str:
    """Replace the RHS of a top-level assignment, preserving the LHS annotation."""
    start_line, end_line = _find_assignment_range(source, var_name)
    prefix = _annotation_prefix(source, var_name)
    lines = source.splitlines(keepends=True)
    before = "".join(lines[: start_line - 1])
    after = "".join(lines[end_line:])
    # Preserve trailing newline of the replaced assignment if the last kept
    # line had one.
    newline = "\n" if not new_value_literal.endswith("\n") else ""
    return before + prefix + new_value_literal + newline + after


def _build_new_source(
    source: str,
    values: Dict[str, Any],
) -> str:
    """Apply every known symbol rewrite to `source` bottom-up and return it."""
    # Edit in reverse order of occurrence so earlier line ranges stay valid.
    symbol_ranges: List[Tuple[str, int]] = []
    for sym in _DICT_SYMBOLS + _LIST_SYMBOLS:
        if sym not in values:
            continue
        try:
            start, _end = _find_assignment_range(source, sym)
        except ValueError:
            continue
        symbol_ranges.append((sym, start))
    symbol_ranges.sort(key=lambda x: -x[1])

    out = source
    for sym, _start in symbol_ranges:
        val = values[sym]
        if sym in ("TRADE_AREA_PRIORS", "BUSINESS_TYPE_PRIORS",
                   "DAYPART_PRIORS", "WEATHER_PRIORS"):
            literal = _render_nested_priors(val)
        elif sym in ("DEFAULT_TRADE", "DEFAULT_TYPE"):
            literal = _render_flat_priors(val)
        elif sym == "DAYPART_WINDOWS":
            windows = [(n, int(s), int(e)) for n, s, e in val]
            literal = _render_daypart_windows(windows)
        else:
            continue
        out = _splice_assignment(out, sym, literal)
    return out


def _validate_rewritten(new_source: str) -> None:
    """Make sure the rewrite parses and the assignments still exist + are well-typed."""
    tree = ast.parse(new_source)  # will raise SyntaxError if malformed
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    for required in _DICT_SYMBOLS + _LIST_SYMBOLS:
        if required not in names:
            raise ValueError(f"rewrite dropped the assignment for {required!r}")


# --------------------------------------------------------------- extract values
def _values_from_learned_json(path: Path, *, include_windows: bool) -> Dict[str, Any]:
    """Pull the `effective` block out of a learned-params JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    eff = payload.get("effective")
    if not eff:
        raise ValueError(f"{path} has no 'effective' block — is this a learned-params JSON?")

    def _canonical(d: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
        return {k: {a: float(v[a]) for a in _AXES if a in v} for k, v in d.items()}

    out: Dict[str, Any] = {
        "TRADE_AREA_PRIORS": _canonical(eff["trade"]),
        "BUSINESS_TYPE_PRIORS": _canonical(eff["type"]),
        "DAYPART_PRIORS": _canonical(eff["daypart"]),
        "WEATHER_PRIORS": _canonical(eff["weather"]),
        "DEFAULT_TRADE": {a: float(eff["default_trade"][a]) for a in _AXES},
        "DEFAULT_TYPE": {a: float(eff["default_type"][a]) for a in _AXES},
    }
    if include_windows:
        # Reconstruct updated DAYPART_WINDOWS by applying learned window shifts.
        # We go through offsets → effective_daypart_windows for correctness.
        from .export_params import params_from_dict
        from .offsets import effective_daypart_windows
        params = params_from_dict(payload["offsets"])
        out["DAYPART_WINDOWS"] = [(n, int(s), int(e))
                                  for n, s, e in effective_daypart_windows(params)]
    return out


# --------------------------------------------------------------- backup & diff
def _backup_current() -> Path:
    ensure_output_dirs()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = BACKUP_DIR / f"ambience_service.{ts}.py"
    shutil.copy2(AMBIENCE_FILE, path)
    return path


def _diff_summary(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """Produce a short list of 'SYMBOL[key].axis: old → new' strings for logging."""
    diffs: List[str] = []
    for sym in _DICT_SYMBOLS:
        b = before.get(sym, {})
        a = after.get(sym, {})
        if sym in ("DEFAULT_TRADE", "DEFAULT_TYPE"):
            for axis in _AXES:
                if axis in b and axis in a and abs(b[axis] - a[axis]) > 1e-4:
                    diffs.append(f"{sym}.{axis}: {b[axis]:.3f} → {a[axis]:.3f}")
            continue
        for key in sorted(set(b) | set(a)):
            vb = b.get(key, {})
            va = a.get(key, {})
            for axis in _AXES:
                x, y = vb.get(axis), va.get(axis)
                if x is None and y is None:
                    continue
                if x is None or y is None or abs(x - y) > 1e-4:
                    diffs.append(
                        f"{sym}[{key!r}].{axis}: {x if x is None else f'{x:.3f}'} → "
                        f"{y if y is None else f'{y:.3f}'}"
                    )
    # DAYPART_WINDOWS diff (tuples)
    b_w = before.get("DAYPART_WINDOWS", [])
    a_w = after.get("DAYPART_WINDOWS", [])
    if b_w != a_w:
        diffs.append(f"DAYPART_WINDOWS: {b_w} → {a_w}")
    return diffs


# --------------------------------------------------------------- public API
def apply_from_learned(
    learned_json: Path,
    *,
    include_windows: bool = True,
    dry_run: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Rewrite ambience_service.py using the effective tables in `learned_json`."""
    ensure_output_dirs()
    _ensure_baseline_snapshot()  # capture pristine values if not already captured

    before = _read_current_values()
    target_values = _values_from_learned_json(learned_json, include_windows=include_windows)

    source = AMBIENCE_FILE.read_text(encoding="utf-8")
    new_source = _build_new_source(source, target_values)
    _validate_rewritten(new_source)

    diffs = _diff_summary(before, target_values)

    result: Dict[str, Any] = {
        "mode": "apply",
        "learned_json": str(learned_json),
        "diff": diffs,
        "dry_run": dry_run,
    }

    if dry_run:
        if verbose:
            _safe_print(f"[dry-run] Would edit {AMBIENCE_FILE}")
            _safe_print(f"[dry-run] Baseline snapshot: {BASELINE_SNAPSHOT}")
            _safe_print(f"[dry-run] {len(diffs)} value(s) would change:")
            for line in diffs[:40]:
                _safe_print(f"    {line}")
            if len(diffs) > 40:
                _safe_print(f"    ... and {len(diffs) - 40} more")
        return result

    backup_path = _backup_current()
    AMBIENCE_FILE.write_text(new_source, encoding="utf-8")
    result["backup"] = str(backup_path)

    # Final sanity: re-read via module import to confirm the new file parses.
    _read_current_values()

    if verbose:
        _safe_print(f"Edited {AMBIENCE_FILE}")
        _safe_print(f"Backup  -> {backup_path}")
        _safe_print(f"Changed {len(diffs)} value(s):")
        for line in diffs[:40]:
            _safe_print(f"    {line}")
        if len(diffs) > 40:
            _safe_print(f"    ... and {len(diffs) - 40} more")
    return result


def restore_defaults(*, dry_run: bool = False, verbose: bool = True) -> Dict[str, Any]:
    """Write the priors captured in the baseline snapshot back into ambience_service.py."""
    if not BASELINE_SNAPSHOT.exists():
        raise FileNotFoundError(
            f"No baseline snapshot at {BASELINE_SNAPSHOT}. "
            "Nothing to restore — the snapshot is created automatically on the "
            "first successful apply. If you want to re-capture the current "
            "state as the new baseline, simply run an `apply` against the "
            "current production values."
        )
    payload = json.loads(BASELINE_SNAPSHOT.read_text(encoding="utf-8"))
    target_values = payload["values"]
    before = _read_current_values()

    source = AMBIENCE_FILE.read_text(encoding="utf-8")
    new_source = _build_new_source(source, target_values)
    _validate_rewritten(new_source)

    diffs = _diff_summary(before, target_values)
    result: Dict[str, Any] = {
        "mode": "restore",
        "snapshot": str(BASELINE_SNAPSHOT),
        "captured_at": payload.get("captured_at"),
        "diff": diffs,
        "dry_run": dry_run,
    }

    if dry_run:
        if verbose:
            _safe_print(f"[dry-run] Would restore {AMBIENCE_FILE} from snapshot {BASELINE_SNAPSHOT}")
            _safe_print(f"[dry-run] {len(diffs)} value(s) would change:")
            for line in diffs[:40]:
                _safe_print(f"    {line}")
            if len(diffs) > 40:
                _safe_print(f"    ... and {len(diffs) - 40} more")
        return result

    backup_path = _backup_current()
    AMBIENCE_FILE.write_text(new_source, encoding="utf-8")
    result["backup"] = str(backup_path)
    _read_current_values()  # final parse sanity check

    if verbose:
        _safe_print(f"Restored {AMBIENCE_FILE} from {BASELINE_SNAPSHOT}")
        _safe_print(f"Backup   -> {backup_path}")
        _safe_print(f"Reverted {len(diffs)} value(s).")
    return result


# --------------------------------------------------------------- CLI
def _cli(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description="Apply learned priors to ambience_service.py, or restore defaults.",
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="from_path", default=None,
                       help="path to a learned-params JSON under outputs/rl_calibration/learned_params/")
    group.add_argument("--restore", action="store_true",
                       help="restore the priors captured in the baseline snapshot")
    ap.add_argument("--no-windows", action="store_true",
                    help="do not rewrite DAYPART_WINDOWS even if learned shifts are present")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned edits without touching any file")
    ap.add_argument("--quiet", action="store_true", help="suppress stdout logs")
    args = ap.parse_args(argv)

    verbose = not args.quiet
    if args.restore:
        restore_defaults(dry_run=args.dry_run, verbose=verbose)
    else:
        apply_from_learned(
            Path(args.from_path),
            include_windows=not args.no_windows,
            dry_run=args.dry_run,
            verbose=verbose,
        )


if __name__ == "__main__":
    _cli()
