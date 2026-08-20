"""Streamlit interface for Hotfix Unifier."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from merger import merge_sql, preview_order
from validator import MAX_FILES, ValidationError, validate_files

st.set_page_config(page_title="Hotfix Unifier", page_icon="🛠️")

_BUILD_TIME = datetime.fromtimestamp(Path(__file__).stat().st_mtime).strftime(
    "%d/%m/%Y %H:%M"
)

OUTPUT_KEYS = ("sql_output", "sql_notices")


def _clear_screen() -> None:
    st.session_state["uploader_key"] = st.session_state.get("uploader_key", 0) + 1
    st.session_state["manual_slots"] = 1
    for key in OUTPUT_KEYS:
        st.session_state.pop(key, None)
    for key in [k for k in st.session_state if k.startswith("manual_slot_")]:
        st.session_state.pop(key, None)


def _remove_manual_slot(position: int) -> None:
    total = st.session_state["manual_slots"]
    for i in range(position, total):
        source_key = f"manual_slot_{i + 1}"
        target_key = f"manual_slot_{i}"
        if source_key in st.session_state:
            st.session_state[target_key] = st.session_state[source_key]
        else:
            st.session_state.pop(target_key, None)
    st.session_state.pop(f"manual_slot_{total}", None)
    st.session_state["manual_slots"] = max(1, total - 1)


st.markdown(
    """
    <style>
    .st-key-clear_button button {
        background-color: #d32f2f;
        color: white;
        border: 1px solid #a52a2a;
        border-radius: 8px;
        padding: 0.5rem 1.1rem;
        font-weight: 600;
        white-space: nowrap;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
        transition: background-color 0.15s ease;
    }
    .st-key-clear_button button p {
        white-space: nowrap;
    }
    .st-key-clear_button button:hover {
        background-color: #a52a2a;
        color: white;
        border-color: #8e0000;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

title_col, clear_col = st.columns([4, 2])
with title_col:
    st.title("Hotfix Unifier")
    st.caption(f"Build: {_BUILD_TIME}")
with clear_col:
    st.write("")
    st.write("")
    if st.button("🗑️ Limpar tela", key="clear_button"):
        _clear_screen()
        st.rerun()

st.session_state.setdefault("uploader_key", 0)
uploaded_files = st.file_uploader(
    "Selecione os arquivos de Hotfix (.sql, .sp e .txt). "
    "Voce pode reenviar um Hotfix_Unificada.sql anterior junto com as novas hotfixes.",
    accept_multiple_files=True,
    key=f"uploader_{st.session_state['uploader_key']}",
)

file_count = len(uploaded_files) if uploaded_files else 0
over_limit = file_count > MAX_FILES
manual_sequence: list[str] = []

if uploaded_files:
    st.subheader("Arquivos carregados")
    for file in uploaded_files:
        st.write(f"- {file.name}")
    st.write(f"**Quantidade:** {file_count} / {MAX_FILES}")
    if over_limit:
        st.error("Limite máximo de 20 arquivos.")

    if len(uploaded_files) > 1:
        with st.expander("Ordem manual (opcional)"):
            st.caption(
                "Monte a sequência dos arquivos que precisam rodar numa ordem "
                "específica (ex.: um ajuste de dados antes ou depois de uma procedure). "
                "Os arquivos que você não incluir aqui entram normalmente depois, "
                "pela classificação automática."
            )

            file_names = [file.name for file in uploaded_files]
            st.session_state.setdefault("manual_slots", 1)
            st.session_state["manual_slots"] = min(
                st.session_state["manual_slots"], len(file_names)
            )

            picked: set[str] = set()
            for position in range(1, st.session_state["manual_slots"] + 1):
                available = ["Nenhum"] + [n for n in file_names if n not in picked]
                slot_key = f"manual_slot_{position}"
                if st.session_state.get(slot_key) not in available:
                    st.session_state.pop(slot_key, None)

                select_col, trash_col = st.columns([6, 1])
                with select_col:
                    choice = st.selectbox(f"{position} -", available, key=slot_key)
                with trash_col:
                    st.write("")
                    if st.button("🗑️", key=f"remove_slot_{position}"):
                        _remove_manual_slot(position)
                        st.rerun()

                if choice != "Nenhum":
                    manual_sequence.append(choice)
                    picked.add(choice)

            if st.session_state["manual_slots"] < len(file_names):
                if st.button("+ Adicionar posição"):
                    st.session_state["manual_slots"] += 1
                    st.rerun()

            st.markdown("**Prévia da ordem final (arquitetura da unificação):**")
            try:
                preview_contents = validate_files(uploaded_files)
                order = preview_order(preview_contents, manual_sequence)
                st.code(" → ".join(order), language=None)
            except ValidationError:
                st.caption(
                    "A prévia aparece aqui assim que todos os arquivos forem válidos."
                )

if st.button("Unificar Hotfix", disabled=not uploaded_files or over_limit):
    try:
        contents = validate_files(uploaded_files)
        sql_output, notices = merge_sql(contents, manual_sequence)
        st.session_state["sql_output"] = sql_output
        st.session_state["sql_notices"] = notices
        st.success("Hotfix unificada com sucesso!")
    except ValidationError as error:
        for key in OUTPUT_KEYS:
            st.session_state.pop(key, None)
        st.error(str(error))

if all(key in st.session_state for key in OUTPUT_KEYS):
    for notice in st.session_state["sql_notices"]:
        st.info(notice)

    _, center_col, _ = st.columns([1, 1, 1])
    with center_col:
        st.download_button(
            "Baixar Hotfix_Unificada.sql",
            data=st.session_state["sql_output"],
            file_name="Hotfix_Unificada.sql",
            mime="text/plain",
        )
