from merger import merge_sql, preview_order

TABLE_DDL = "ALTER TABLE PEDIDOS ADD DESCONTO NUMERIC(18,2);"
STUB = """CREATE OR ALTER PROCEDURE CALC (IDPEDIDO BIGINT)
RETURNS (TOTAL NUMERIC(18,2))
AS
BEGIN
  SUSPEND;
END"""
BODY = """CREATE OR ALTER PROCEDURE CALC (IDPEDIDO BIGINT)
RETURNS (TOTAL NUMERIC(18,2))
AS
DECLARE VARIABLE X INTEGER;
BEGIN
  X = 1;
  TOTAL = 10;
  SUSPEND;
END"""
TRIGGER = """CREATE OR ALTER TRIGGER TG_PEDIDOS FOR PEDIDOS
ACTIVE AFTER UPDATE POSITION 0
AS
BEGIN
  INSERT INTO LOG (ID) VALUES (NEW.ID);
END"""
VIEW = "CREATE OR ALTER VIEW VW_ABERTOS AS SELECT ID FROM PEDIDOS WHERE STATUS = 'A';"
GRANT = "GRANT EXECUTE ON PROCEDURE CALC TO PUBLIC;"


def test_orders_by_dependency_stage_not_by_upload_order():
    contents = [
        ("z_grant.sql", GRANT),
        ("m_view.sql", VIEW),
        ("a_body.sp", BODY),
        ("b_table.sql", TABLE_DDL),
    ]
    assert preview_order(contents) == [
        "b_table.sql",
        "a_body.sp",
        "m_view.sql",
        "z_grant.sql",
    ]


def test_signature_stub_runs_before_full_implementation():
    contents = [("impl.sp", BODY.replace("CALC", "OUTRA")), ("sig.sp", STUB)]
    assert preview_order(contents) == ["sig.sp", "impl.sp"]


def test_wraps_procedure_in_set_term():
    output, _ = merge_sql([("calc.sp", BODY)])
    assert "SET TERM ^ ;" in output
    assert output.rstrip().endswith("SET TERM ; ^")


def test_does_not_double_wrap_when_file_manages_its_own_terminator():
    already_wrapped = f"SET TERM ^ ;\n\n{BODY}\n^\n\nSET TERM ; ^"
    output, _ = merge_sql([("calc.sp", already_wrapped)])
    assert output.count("SET TERM ^ ;") == 1


def test_plain_dml_is_not_wrapped():
    output, _ = merge_sql([("ajuste.sql", "UPDATE PEDIDOS SET STATUS = 'OK';")])
    assert "SET TERM" not in output


def test_category_banner_is_emitted_once_per_category():
    contents = [("t1.sql", TABLE_DDL), ("t2.sql", "CREATE INDEX IX ON PEDIDOS (ID);")]
    output, _ = merge_sql(contents)
    assert output.count("-- ==== TABELAS (estrutura) ====") == 1


def test_original_sql_text_is_never_rewritten():
    output, _ = merge_sql([("calc.sp", BODY)])
    assert BODY in output


def test_reimported_bundle_is_unpacked_and_new_version_wins():
    bundle, _ = merge_sql([("calc.sp", BODY), ("trg.sp", TRIGGER)])
    novo = BODY.replace("TOTAL = 10;", "TOTAL = 99;")

    output, notices = merge_sql([("Hotfix_Unificada.sql", bundle), ("calc.sp", novo)])

    assert "TOTAL = 99;" in output
    assert "TOTAL = 10;" not in output
    assert output.count("CREATE OR ALTER PROCEDURE CALC") == 1
    assert any("atualizado para a versao" in n for n in notices)


def test_reimporting_identical_object_reports_no_change():
    bundle, _ = merge_sql([("calc.sp", BODY), ("trg.sp", TRIGGER)])
    _, notices = merge_sql([("Hotfix_Unificada.sql", bundle), ("calc.sp", BODY)])
    assert any("sem mudancas" in n for n in notices)


def test_two_new_hotfixes_for_same_object_raise_ambiguity_warning():
    outra = BODY.replace("TOTAL = 10;", "TOTAL = 20;")
    _, notices = merge_sql([("a_calc.sp", BODY), ("b_calc.sp", outra)])
    assert any("MULTIPLAS hotfixes novas" in n for n in notices)


def test_table_ddl_is_never_deduplicated():
    # Two hotfixes touching the same table usually add different columns —
    # dropping one would silently lose a real change.
    contents = [
        ("t1.sql", "ALTER TABLE PEDIDOS ADD A INTEGER;"),
        ("t2.sql", "ALTER TABLE PEDIDOS ADD B INTEGER;"),
    ]
    output, _ = merge_sql(contents)
    assert "ADD A INTEGER" in output and "ADD B INTEGER" in output


def test_manual_sequence_pins_files_to_the_front():
    contents = [("tabela.sql", TABLE_DDL), ("ajuste.sql", GRANT), ("calc.sp", BODY)]
    order = preview_order(contents, manual_sequence=["ajuste.sql", "calc.sp"])
    assert order[:2] == ["ajuste.sql", "calc.sp"]
    assert order[2] == "tabela.sql"


def test_manual_sequence_ignores_unknown_filenames():
    contents = [("tabela.sql", TABLE_DDL), ("calc.sp", BODY)]
    order = preview_order(contents, manual_sequence=["nao_existe.sql", "calc.sp"])
    assert order == ["calc.sp", "tabela.sql"]


def test_manual_sequence_emits_notice():
    _, notices = merge_sql([("a.sql", TABLE_DDL), ("b.sp", BODY)], ["b.sp"])
    assert any("Ordem manual" in n for n in notices)
