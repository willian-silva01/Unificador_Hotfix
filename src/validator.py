"""Validation rules for uploaded Hotfix files."""
from __future__ import annotations

import re
from typing import Protocol, Sequence

MAX_FILES = 20
ALLOWED_EXTENSIONS = (".sql", ".sp", ".txt")
SQL_KEYWORDS = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "ALTER",
    "CREATE",
    "DROP",
    "EXECUTE",
    "COMMIT",
    "ROLLBACK",
)
_SQL_KEYWORD_PATTERN = re.compile(r"\b(" + "|".join(SQL_KEYWORDS) + r")\b", re.IGNORECASE)


class UploadedFileLike(Protocol):
    """Minimal shape required from an uploaded file (matches Streamlit's UploadedFile)."""

    name: str

    def getvalue(self) -> bytes: ...


class ValidationError(Exception):
    """Raised when an uploaded file or batch of files fails validation."""


def validate_file_count(files: Sequence[UploadedFileLike]) -> None:
    if len(files) > MAX_FILES:
        raise ValidationError("Limite máximo de 20 arquivos.")


def validate_extension(filename: str) -> None:
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise ValidationError("Arquivo inválido. Apenas arquivos .sql, .sp e .txt são permitidos.")


def _decode_text(filename: str, content: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError(f"O arquivo {filename} não é um arquivo de texto legível.")


def validate_sql_content(filename: str, content: bytes) -> str:
    """.sql, .sp and .txt are all treated as hotfix scripts: whichever extension is
    used, the content must contain a recognizable SQL command to be merged."""
    text = _decode_text(filename, content)
    if not _SQL_KEYWORD_PATTERN.search(text):
        raise ValidationError(f"O arquivo {filename} não parece ser uma Hotfix válida.")
    return text


def validate_files(files: Sequence[UploadedFileLike]) -> list[tuple[str, str]]:
    """Validate every uploaded file and return (filename, decoded content) pairs, in upload order.

    A list (not a dict) is used because two uploaded files can share the same name,
    and each must still be kept and merged separately.
    """
    validate_file_count(files)
    contents: list[tuple[str, str]] = []
    for file in files:
        validate_extension(file.name)
        text = validate_sql_content(file.name, file.getvalue())
        contents.append((file.name, text))
    return contents
