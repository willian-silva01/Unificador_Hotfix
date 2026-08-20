@echo off
REM Sobe o Hotfix Unifier acessivel na rede local (porta 8501).
REM Usa o Python do PATH — ajuste a linha abaixo se precisar de um interpretador especifico.
cd /d "%~dp0\.."
python -m streamlit run src/app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
