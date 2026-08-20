"""Ordering and merging logic for Hotfix files."""
from __future__ import annotations

import re

_DASH_SUFFIX = "-" * 40
_TERMINATOR = "^"
SQL_OUTPUT_EXTENSIONS = (".sql", ".sp", ".txt")

_PROCEDURAL_BLOCK_PATTERN = re.compile(
    r"^\s*("
    r"CREATE\s+(OR\s+ALTER\s+)?PROCEDURE|ALTER\s+PROCEDURE|"
    r"CREATE\s+(OR\s+ALTER\s+)?TRIGGER|ALTER\s+TRIGGER|"
    r"CREATE\s+(OR\s+ALTER\s+)?FUNCTION|ALTER\s+FUNCTION|"
    r"EXECUTE\s+BLOCK"
    r")\b",
    re.IGNORECASE,
)


def _needs_terminator_wrap(text: str) -> bool:
    """A procedure/trigger/function body has internal ';' and needs its own SET TERM
    so a script executor treats it as one statement instead of splitting on every ';'."""
    return bool(_PROCEDURAL_BLOCK_PATTERN.match(text)) and "SET TERM" not in text.upper()


def _wrap_with_terminator(text: str) -> str:
    return (
        f"SET TERM {_TERMINATOR} ;\n\n"
        f"{text.rstrip()}\n{_TERMINATOR}\n\n"
        f"SET TERM ; {_TERMINATOR}"
    )


# Execution order: table/index structure must exist before procedures can reference it;
# procedure signatures must exist before other procedures can call them with new params;
# only then can the real procedure bodies, triggers, views and finally data/grants run.
_TABLE_DDL_PATTERN = re.compile(
    r"\b(CREATE\s+TABLE|ALTER\s+TABLE|"
    r"CREATE\s+(UNIQUE\s+)?(ASC(ENDING)?\s+|DESC(ENDING)?\s+)?INDEX|ALTER\s+INDEX|"
    r"CREATE\s+DOMAIN|ALTER\s+DOMAIN)\b",
    re.IGNORECASE,
)
_PROCEDURE_OR_FUNCTION_PATTERN = re.compile(
    r"\bCREATE\s+(OR\s+ALTER\s+)?(PROCEDURE|FUNCTION)\b|\bALTER\s+(PROCEDURE|FUNCTION)\b",
    re.IGNORECASE,
)
_TRIGGER_PATTERN = re.compile(
    r"\bCREATE\s+(OR\s+ALTER\s+)?TRIGGER\b|\bALTER\s+TRIGGER\b",
    re.IGNORECASE,
)
_VIEW_PATTERN = re.compile(
    r"\bCREATE\s+(OR\s+ALTER\s+)?VIEW\b|\bALTER\s+VIEW\b|\bRECREATE\s+VIEW\b",
    re.IGNORECASE,
)
_BEGIN_PATTERN = re.compile(r"\bBEGIN\b", re.IGNORECASE)
_END_PATTERN = re.compile(r"\bEND\b", re.IGNORECASE)
_LINE_COMMENT_PATTERN = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)

CATEGORY_LABELS = {
    1: "TABELAS (estrutura)",
    2: "ASSINATURA DE PROCEDURES/FUNCTIONS",
    3: "IMPLEMENTACAO DE PROCEDURES/FUNCTIONS",
    4: "TRIGGERS",
    5: "VIEWS",
    6: "AJUSTES FINAIS (grants, inserts, updates, etc.)",
}

# Only these categories hold objects that are redefined wholesale by CREATE OR ALTER,
# so only these get replace-by-name version resolution. Table DDL and final adjustments
# (grants/inserts/updates) are cumulative across hotfixes and are never deduplicated.
_VERSIONED_CATEGORIES = {2, 3, 4, 5}

_OBJECT_IDENTITY_PATTERN = re.compile(
    r"\b(CREATE|ALTER|RECREATE)\s+(OR\s+ALTER\s+)?(PROCEDURE|TRIGGER|VIEW|FUNCTION)\s+"
    r"(\"[^\"]+\"|[A-Za-z_$][A-Za-z0-9_$]*)",
    re.IGNORECASE,
)

# Marks a file previously produced by merge_sql itself, so it can be re-imported and
# unpacked back into its individual hotfix blocks instead of being treated as one opaque file.
_BUNDLE_HEADER_PATTERN = re.compile(r"^-- Hotfix: (.+?) -{5,}\s*$", re.MULTILINE)
_BUNDLE_BANNER_PATTERN = re.compile(r"^-- ==== .+ ====\s*$", re.MULTILINE)


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT_PATTERN.sub("", text)
    return _LINE_COMMENT_PATTERN.sub("", text)


def _is_stub_procedure_body(text: str) -> bool:
    """A signature-only stub has nothing between BEGIN/END besides an optional SUSPEND."""
    clean = _strip_comments(text)
    begin_match = _BEGIN_PATTERN.search(clean)
    end_matches = list(_END_PATTERN.finditer(clean))
    if not begin_match or not end_matches:
        return False
    body = clean[begin_match.end() : end_matches[-1].start()].strip().rstrip(";").strip()
    return body == "" or body.upper() == "SUSPEND"


def _classify_category(text: str) -> int:
    if _TABLE_DDL_PATTERN.search(text):
        return 1
    if _PROCEDURE_OR_FUNCTION_PATTERN.search(text):
        return 2 if _is_stub_procedure_body(text) else 3
    if _TRIGGER_PATTERN.search(text):
        return 4
    if _VIEW_PATTERN.search(text):
        return 5
    return 6


def _extract_object_identity(text: str) -> tuple[str, str] | None:
    match = _OBJECT_IDENTITY_PATTERN.search(text)
    if not match:
        return None
    return (match.group(3).upper(), match.group(4).strip('"').upper())


_WRAPPED_TERMINATOR_PATTERN = re.compile(
    r"^SET\s+TERM\s+\^\s*;\s*(.*?)\s*\^\s*SET\s+TERM\s*;\s*\^\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _unwrap_terminator(text: str) -> str:
    """Undo _wrap_with_terminator so a bundle-extracted block compares equal to the
    same statement freshly uploaded without a SET TERM wrapper around it yet."""
    match = _WRAPPED_TERMINATOR_PATTERN.match(text.strip())
    return match.group(1) if match else text


def _normalize_for_comparison(text: str) -> str:
    return re.sub(r"\s+", " ", _unwrap_terminator(text)).strip().upper()


def _describe_source(name: str, is_from_bundle: bool) -> str:
    return f"'{name}' (do unificado anterior)" if is_from_bundle else f"'{name}' (novo upload)"


def _split_bundle(text: str) -> list[tuple[str, str]] | None:
    """If text is a previously merged Hotfix_Unificada.sql, split it back into its
    original (filename, content) blocks. Returns None if text isn't a bundle."""
    matches = list(_BUNDLE_HEADER_PATTERN.finditer(text))
    if len(matches) < 2:
        return None
    entries = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = _BUNDLE_BANNER_PATTERN.sub("", text[start:end]).strip("\n")
        entries.append((match.group(1).strip(), chunk))
    return entries


def _expand_bundles(matched: list[tuple[str, str]]) -> list[tuple[str, str, bool]]:
    """Returns (name, text, is_from_bundle) triples, unpacking any previously unified
    files back into their individual hotfix blocks so they can be re-versioned."""
    expanded: list[tuple[str, str, bool]] = []
    for name, text in matched:
        sub_entries = _split_bundle(text)
        if sub_entries is None:
            expanded.append((name, text, False))
        else:
            expanded.extend((sub_name, sub_text, True) for sub_name, sub_text in sub_entries)
    return expanded


def _resolve_versions(
    entries: list[tuple[str, str, bool]],
) -> tuple[list[tuple[str, str, bool]], list[str]]:
    """Keep only the newest definition of each CREATE-OR-ALTER-style object.

    A fresh upload always wins over a definition unpacked from an imported bundle.
    Everything else (table DDL, grants/inserts, objects whose name couldn't be
    parsed) is kept as-is, with no deduplication.

    The winner is emitted at the position of the group's *first* occurrence, so a
    fresh file that replaces one object inside an imported bundle stays exactly where
    that object was, instead of jumping elsewhere. Each kept entry is tagged
    "structural" (True) when any version of it came from an imported bundle, so the
    caller can keep that pre-existing structure untouched by default and only
    reorder/append genuinely new content. Returns (kept, notices).
    """
    groups: dict[tuple[str, str], list[tuple[str, str, bool]]] = {}
    for name, text, is_from_bundle in entries:
        category = _classify_category(text)
        identity = _extract_object_identity(text) if category in _VERSIONED_CATEGORIES else None
        if identity is not None:
            groups.setdefault(identity, []).append((name, text, is_from_bundle))

    winners: dict[tuple[str, str], tuple[str, str, bool]] = {}
    notices: list[str] = []
    for identity, group in groups.items():
        obj_type, obj_name = identity
        if len(group) == 1:
            winners[identity] = group[0]
            continue

        fresh = [item for item in group if not item[2]]
        candidates = fresh if fresh else group
        winner = max(candidates, key=lambda item: item[0])
        losers = [item for item in group if item is not winner]
        winner_label = _describe_source(winner[0], winner[2])
        loser_labels = ", ".join(_describe_source(item[0], item[2]) for item in losers)
        identical = all(
            _normalize_for_comparison(item[1]) == _normalize_for_comparison(winner[1])
            for item in group
        )

        if identical:
            notices.append(f"{obj_type} {obj_name}: sem mudancas (identico em {loser_labels}).")
        elif len(fresh) > 1:
            fresh_labels = ", ".join(_describe_source(item[0], item[2]) for item in fresh)
            notices.append(
                f"{obj_type} {obj_name}: MULTIPLAS hotfixes novas definem este objeto "
                f"({fresh_labels}); mantida {winner_label} por ordem alfabetica - "
                f"confira se e a versao correta."
            )
        else:
            notices.append(
                f"{obj_type} {obj_name}: atualizado para a versao de {winner_label} "
                f"(substituiu {loser_labels})."
            )
        is_structural = any(item[2] for item in group)
        winners[identity] = (winner[0], winner[1], is_structural)

    kept: list[tuple[str, str, bool]] = []
    emitted: set[tuple[str, str]] = set()
    for name, text, is_from_bundle in entries:
        category = _classify_category(text)
        identity = _extract_object_identity(text) if category in _VERSIONED_CATEGORIES else None
        if identity is None:
            kept.append((name, text, is_from_bundle))
        elif identity not in emitted:
            kept.append(winners[identity])
            emitted.add(identity)

    return kept, notices


def _filter_by_extension(
    contents: list[tuple[str, str]], extensions: str | tuple[str, ...]
) -> list[tuple[str, str]]:
    return [item for item in contents if item[0].lower().endswith(extensions)]


def _default_order(resolved: list[tuple[str, str, bool]]) -> list[tuple[str, str]]:
    """No manual sequence given. Entries that came from a re-imported bundle (directly,
    or as the replacement for something that was in it) keep their existing relative
    order untouched, exactly as the previous unification left it. Genuinely new
    entries are classified and sorted by category as usual, then appended after.

    When nothing came from a bundle, this is identical to the original behavior:
    everything sorted by (category, filename).
    """
    structural = [(name, text) for name, text, is_structural in resolved if is_structural]
    fresh = [(name, text) for name, text, is_structural in resolved if not is_structural]
    fresh.sort(key=lambda item: (_classify_category(item[1]), item[0]))
    return structural + fresh


def _apply_manual_sequence(
    resolved: list[tuple[str, str, bool]], manual_sequence: list[str]
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pin specific files to run first, in the exact order given (position 1, 2, 3...).
    Every other file keeps its default order (see `_default_order`) and is appended
    after them.

    A plain ordered list (not pairwise "after" relationships) so it's impossible to
    create a contradiction: a file can only occupy one position.
    """
    if not manual_sequence:
        return _default_order(resolved), []

    by_name = {name: text for name, text, _ in resolved}
    pinned: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in manual_sequence:
        if name in by_name and name not in seen:
            pinned.append((name, by_name[name]))
            seen.add(name)

    remaining = [item for item in resolved if item[0] not in seen]
    remaining_ordered = _default_order(remaining)

    notices = []
    if pinned:
        notices.append(
            "Ordem manual fixada no início: "
            + " -> ".join(name for name, _ in pinned)
            + " (demais arquivos seguem a ordem automática logo em seguida)."
        )
    return pinned + remaining_ordered, notices


def _compute_final_order(
    contents: list[tuple[str, str]], manual_sequence: list[str] | None = None
) -> tuple[list[tuple[str, str]], list[str]]:
    matched = _filter_by_extension(contents, SQL_OUTPUT_EXTENSIONS)
    entries = _expand_bundles(matched)
    resolved, notices = _resolve_versions(entries)
    ordered, order_notices = _apply_manual_sequence(resolved, manual_sequence or [])
    return ordered, notices + order_notices


def preview_order(
    contents: list[tuple[str, str]], manual_sequence: list[str] | None = None
) -> list[str]:
    """Return just the final filename order (no SQL text), so the UI can show what
    the resulting script will look like before the user commits to unifying."""
    ordered, _ = _compute_final_order(contents, manual_sequence)
    return [name for name, _ in ordered]


def merge_sql(
    contents: list[tuple[str, str]], manual_sequence: list[str] | None = None
) -> tuple[str, list[str]]:
    """Merge all .sql, .sp and .txt contents into a single SQL file, preserving each
    command as-is.

    Previously generated Hotfix_Unificada.sql files can be re-uploaded alongside new
    hotfixes: they are unpacked back into their original blocks, and any object
    (procedure/trigger/view/function) redefined by a new hotfix replaces the old one
    instead of being duplicated. Blocks are then ordered by dependency stage (tables,
    procedure signatures, procedure bodies, triggers, views, then everything else).
    Procedures/triggers/functions that don't already manage their own terminator get
    wrapped in SET TERM so the merged script can run as a single batch.

    `manual_sequence` optionally pins specific filenames to run first, in that exact
    order, for cases the classifier can't infer on its own (e.g. a data-fix UPDATE
    tied to a specific procedure hotfix). Every other file still gets merged normally,
    right after the pinned ones.

    Returns (merged_sql_text, notices) where notices describes any object that was
    replaced or found duplicated during version resolution, plus any manual ordering
    applied.
    """
    ordered, notices = _compute_final_order(contents, manual_sequence)

    blocks = []
    current_category = None
    for name, text in ordered:
        category = _classify_category(text)
        if category != current_category:
            blocks.append(f"-- ==== {CATEGORY_LABELS[category]} ====")
            current_category = category
        header = f"-- Hotfix: {name} {_DASH_SUFFIX}"
        body = _wrap_with_terminator(text) if _needs_terminator_wrap(text) else text
        blocks.append(f"{header}\n\n{body}\n")
    return "\n".join(blocks), notices
