import pytest

from validator import MAX_FILES, ValidationError, validate_files


class FakeUpload:
    """Mimics the two attributes of Streamlit's UploadedFile that we depend on."""

    def __init__(self, name: str, content: bytes | str):
        self.name = name
        self._content = content.encode("utf-8") if isinstance(content, str) else content

    def getvalue(self) -> bytes:
        return self._content


def test_accepts_sql_sp_and_txt():
    files = [
        FakeUpload("a.sql", "SELECT 1 FROM RDB$DATABASE;"),
        FakeUpload("b.sp", "CREATE OR ALTER PROCEDURE P AS BEGIN END"),
        FakeUpload("c.txt", "UPDATE PEDIDOS SET STATUS = 'OK';"),
    ]
    assert [name for name, _ in validate_files(files)] == ["a.sql", "b.sp", "c.txt"]


def test_rejects_unknown_extension():
    with pytest.raises(ValidationError, match="Arquivo inválido"):
        validate_files([FakeUpload("relatorio.pdf", "SELECT 1;")])


def test_rejects_file_without_sql_command():
    with pytest.raises(ValidationError, match="não parece ser uma Hotfix válida"):
        validate_files([FakeUpload("nota.txt", "lembrar de avisar o cliente")])


def test_rejects_batch_over_limit():
    files = [FakeUpload(f"{i}.sql", "SELECT 1;") for i in range(MAX_FILES + 1)]
    with pytest.raises(ValidationError, match="Limite máximo"):
        validate_files(files)


def test_falls_back_to_latin1_when_utf8_fails():
    # Firebird scripts exported by legacy tools frequently arrive as Latin-1.
    content = "SELECT 'DESCRIÇÃO' FROM RDB$DATABASE;".encode("latin-1")
    (_, text), = validate_files([FakeUpload("acento.sql", content)])
    assert "DESCRIÇÃO" in text


def test_duplicate_names_are_both_kept():
    files = [FakeUpload("fix.sql", "SELECT 1;"), FakeUpload("fix.sql", "SELECT 2;")]
    result = validate_files(files)
    assert len(result) == 2
    assert result[0][1] != result[1][1]
