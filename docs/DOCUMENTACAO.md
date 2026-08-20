# Hotfix Unifier — Documentação Técnica

Ferramenta para unificar múltiplos arquivos de Hotfix (`.sql`, `.sp` e `.txt`)
de bancos Firebird/Interbase em um único script SQL pronto para execução, respeitando
a ordem de dependência entre os objetos do banco.

Aplicação stateless — sem autenticação, sem banco de dados, sem histórico persistido.

---

## Índice

1. [Objetivo](#1-objetivo)
2. [Estrutura do projeto](#2-estrutura-do-projeto)
3. [Como usar](#3-como-usar)
4. [Fluxo interno (o que acontece ao clicar em "Unificar Hotfix")](#4-fluxo-interno)
5. [Regras de validação](#5-regras-de-validação)
6. [Ordenação por dependência](#6-ordenação-por-dependência)
7. [Resolução de versão (reimportar um unificado anterior)](#7-resolução-de-versão)
8. [Formato do arquivo gerado](#8-formato-do-arquivo-gerado)
9. [Implantação (como o app fica no ar)](#9-implantação)
10. [Limitações conhecidas](#10-limitações-conhecidas)
11. [Stack técnica](#11-stack-técnica)

---

## 1. Objetivo

Um DBA/desenvolvedor acumula, ao longo de um ciclo de correções, vários arquivos de
hotfix soltos (`001.sql`, `ajuste_estoque.sp`, `nota.txt`, etc.). Rodar cada um
manualmente, na ordem certa, é lento e sujeito a erro — principalmente porque objetos
de banco (procedures, triggers, views) têm dependências entre si: uma procedure pode
chamar outra, uma trigger pode depender de uma coluna nova, etc.

O Hotfix Unifier resolve isso automaticamente:

- Junta todos os arquivos enviados em **um único `Hotfix_Unificada.sql`**.
- Reordena o conteúdo pela sequência segura de execução (tabelas → assinaturas de
  procedures → corpo das procedures → triggers → views → ajustes finais).
- Se um objeto (procedure/trigger/view/function) já existir em uma unificação anterior
  e uma hotfix nova o redefinir, **mantém só a versão mais nova**, em vez de duplicar.
- Não altera nenhuma linha de código enviada — só reordena, agrupa e, quando
  necessário, envolve blocos com `SET TERM` para o script rodar de uma vez só.

---

## 2. Estrutura do projeto

```
├── src/
│   ├── app.py                    # Interface Streamlit (upload, prévia, botão, download)
│   ├── validator.py              # Validação de extensão, conteúdo e limite de arquivos
│   └── merger.py                 # Classificação, ordenação, versionamento e montagem do SQL final
├── examples/                     # Hotfixes sintéticas de exemplo, uma por categoria
├── tests/                        # Suíte pytest
├── docs/DOCUMENTACAO.md          # Este documento
├── scripts/
│   ├── start_hotfix_unifier.bat  # Script que sobe o Streamlit (usado pela Tarefa Agendada)
│   └── setup_scheduled_task.ps1  # Registra a Tarefa Agendada + regra de Firewall (Admin, 1x)
├── requirements.txt              # Dependências de runtime (streamlit)
├── requirements-dev.txt          # Dependências de desenvolvimento (pytest)
├── README.md                     # Guia rápido de instalação/uso
└── LICENSE
```

**Responsabilidade de cada módulo:**

| Módulo | Responsabilidade |
|---|---|
| `validator.py` | Garante que só entram arquivos `.sql`/`.sp`/`.txt` válidos, dentro do limite de 20, com conteúdo SQL reconhecível. |
| `merger.py` | Todo o "cérebro": classifica cada arquivo, decide a ordem, resolve versões duplicadas e monta o texto final. |
| `app.py` | Só a camada visual — chama os dois módulos acima e mostra o resultado. |

---

## 3. Como usar

1. Acesse a URL da aplicação (ex.: `http://localhost:8501`).
2. Selecione até 20 arquivos `.sql`, `.sp` e/ou `.txt` (pode arrastar vários de uma vez).
3. Clique em **Unificar Hotfix**.
4. Se algum arquivo for inválido, a unificação é **cancelada** e o erro aponta
   exatamente qual arquivo e por quê.
5. Se tudo estiver certo, aparecem avisos (quando aplicável — ver seção 7) e o botão
   **Baixar Hotfix_Unificada.sql**.

---

## 4. Fluxo interno

```
Upload (Streamlit)
      │
      ▼
validate_files()          → valida extensão, conteúdo SQL, limite de 20
      │  (lista de (nome, conteúdo), preservando nomes duplicados)
      ▼
merge_sql()
      │
      ├─ 1. Filtra apenas .sql/.sp
      │
      ├─ 2. _expand_bundles()      → se algum arquivo já for um Hotfix_Unificada.sql
      │                              gerado antes, desmonta ele de volta nos blocos
      │                              originais (ver seção 7)
      │
      ├─ 3. _resolve_versions()    → para procedures/triggers/views/functions,
      │                              mantém só a versão mais nova de cada objeto
      │
      ├─ 4. Classifica cada bloco em 1 das 6 categorias (ver seção 6)
      │
      ├─ 5. Ordena por (categoria, nome do arquivo)
      │
      └─ 6. Monta o texto final:
             - insere banner de categoria quando ela muda
             - insere cabeçalho "-- Hotfix: nome.sql ----"
             - envolve em SET TERM quando necessário
      │
      ▼
(Hotfix_Unificada.sql, avisos) → exibido / disponível para download
```

---

## 5. Regras de validação (`validator.py`)

| Regra | Comportamento |
|---|---|
| Extensão permitida | Apenas `.sql`, `.sp`, `.txt`. Qualquer outra: `"Arquivo inválido. Apenas arquivos .sql, .sp e .txt são permitidos."` |
| Limite de arquivos | Máximo 20 por vez. Acima disso: `"Limite máximo de 20 arquivos."` |
| Conteúdo `.sql`/`.sp` | Precisa conter ao menos um destes comandos (busca por palavra inteira, sem diferenciar maiúsculas): `SELECT, INSERT, UPDATE, DELETE, ALTER, CREATE, DROP, EXECUTE, COMMIT, ROLLBACK`. Caso contrário: `"O arquivo X não parece ser uma Hotfix válida."` |
| Conteúdo `.txt` | Só precisa ser texto legível (decodificado em UTF-8 ou, se falhar, Latin-1). |
| Nomes duplicados | Dois arquivos com o mesmo nome **não se sobrescrevem** — ambos são mantidos e processados separadamente. |
| Qualquer erro | **Cancela a unificação inteira** — nada é gerado até todos os arquivos passarem. |

---

## 6. Ordenação por dependência

Cada arquivo `.sql`/`.sp` é classificado em uma de 6 categorias, com base em busca de
padrões no próprio conteúdo (não no nome do arquivo). A saída final segue essa ordem;
dentro de cada categoria, os arquivos ficam em ordem alfabética pelo nome original.

| # | Categoria | Como é detectada |
|---|---|---|
| 1 | **Tabelas (estrutura)** | Contém `CREATE/ALTER TABLE`, `CREATE/ALTER INDEX` ou `CREATE/ALTER DOMAIN`. |
| 2 | **Assinatura de Procedures/Functions** | `CREATE/ALTER PROCEDURE` ou `FUNCTION` cujo corpo (entre `BEGIN` e `END`) está vazio ou contém apenas `SUSPEND;`. |
| 3 | **Implementação de Procedures/Functions** | Mesmo comando, mas com corpo real (lógica de negócio). |
| 4 | **Triggers** | `CREATE/ALTER TRIGGER`. |
| 5 | **Views** | `CREATE/ALTER/RECREATE VIEW`. |
| 6 | **Ajustes finais** | Tudo que não se encaixa acima: `GRANT`, `INSERT`, `UPDATE` de dados, `DELETE`, etc. |

**Por que essa ordem:** tabelas precisam existir antes de qualquer procedure que use
suas colunas; a *assinatura* de uma procedure precisa existir antes de outra procedure
chamá-la com os parâmetros novos; só depois entra a implementação completa; triggers e
views costumam depender de procedures/tabelas já prontas; grants e ajustes de dados
vêm por último.

Cada mudança de categoria gera um comentário `-- ==== NOME DA CATEGORIA ====` no
arquivo final, para facilitar a conferência visual antes de rodar o script.

### SET TERM automático

Procedures, triggers, functions e `EXECUTE BLOCK` que contêm `;` internamente (ex.:
`DECLARE VARIABLE X SMALLINT;`) precisam de um terminador de script diferente do `;`
padrão, senão o executor de script (IBExpert, isql etc.) tenta rodar cada linha interna
como um comando isolado e falha com `Invalid token`. Sempre que um desses blocos **não
já tiver seu próprio `SET TERM`**, a ferramenta envolve automaticamente:

```sql
SET TERM ^ ;

CREATE OR ALTER PROCEDURE ...
AS
BEGIN
  ...
END
^

SET TERM ; ^
```

Se o arquivo original já gerencia seu próprio `SET TERM`, nada é alterado (evita
duplicar o wrapper).

---

## 7. Resolução de versão

Um `Hotfix_Unificada.sql` gerado por esta ferramenta pode ser **reenviado no próximo
ciclo**, junto com as hotfixes novas, sem precisar reconstruir tudo do zero.

**Como funciona:**

1. Ao detectar que um arquivo enviado contém 2 ou mais marcadores `-- Hotfix: nome ----`
   (ou seja, é um unificado anterior), a ferramenta o desmonta de volta nos blocos
   originais — como se cada um tivesse sido enviado separadamente.
2. Para objetos do tipo `CREATE OR ALTER` (procedure, trigger, view, function), o nome
   real do objeto é extraído do próprio comando SQL (não do nome do arquivo).
3. Se o **mesmo objeto** aparecer tanto no unificado importado quanto em um arquivo
   novo, só a versão nova é mantida — a antiga é descartada.
4. A tela mostra um aviso (`st.info`) para cada objeto resolvido, em 3 situações:

| Situação | Mensagem |
|---|---|
| Hotfix nova substitui a versão antiga (conteúdo diferente) | `PROCEDURE FOO: atualizado para a versao de 'foo.sql' (novo upload) (substituiu 'foo.sql' (do unificado anterior)).` |
| Hotfix nova é idêntica à já existente | `PROCEDURE FOO: sem mudancas (identico em 'foo.sql' (do unificado anterior)).` |
| Duas hotfixes novas definem o mesmo objeto no mesmo lote (ambíguo) | `PROCEDURE FOO: MULTIPLAS hotfixes novas definem este objeto (...); mantida '...' por ordem alfabetica - confira se e a versao correta.` |

**O que NÃO é deduplicado:** alterações de tabela (`ALTER TABLE`) e ajustes finais
(`GRANT`/`INSERT`/`UPDATE` de dados) são sempre concatenados, nunca substituídos —
porque hotfixes diferentes de uma mesma tabela costumam adicionar colunas diferentes,
e descartar uma por engano perderia uma alteração real.

**A estrutura do unificado importado é preservada por padrão.** Se o unificado que
você reenviou já tinha uma ordem específica (seja pela classificação automática, seja
por uma ordem manual aplicada da vez anterior), essa ordem **não é refeita do zero**.
Arquivos novos que não substituem nada de dentro do bundle são adicionados **depois**
dela, seguindo a classificação automática normal entre si. Se uma hotfix nova
substitui um objeto que já estava no bundle (seção acima), a versão nova entra
exatamente na posição que a antiga ocupava — a estrutura ao redor não se mexe.

---

## 7.1. Ordem manual (override)

A classificação automática (seção 6) não sabe que um arquivo específico depende de
outro além do que dá para inferir pelo tipo de comando. Para casos assim — por exemplo,
um ajuste de dados (`UPDATE`) que precisa rodar antes e outro que precisa rodar depois
de uma procedure específica — é possível fixar manualmente a sequência de alguns
arquivos, na tela.

Isso fica em um expander opcional **"Ordem manual"**, abaixo da lista de arquivos
carregados (só aparece com 2+ arquivos enviados). A UI mostra posições numeradas
(`1 -`, `2 -`, `3 -`...), cada uma com um seletor para escolher qual arquivo ocupa
aquela posição; um botão **"+ Adicionar posição"** permite incluir mais posições
(até o total de arquivos enviados). Um arquivo só pode ocupar uma posição por vez.

Os arquivos fixados nas posições rodam **primeiro**, exatamente nessa ordem. Todos os
demais arquivos (os que você não incluiu em nenhuma posição) são adicionados **depois**,
seguindo a classificação automática normal (seção 6) — não é preciso posicionar todo
mundo, só o que realmente precisa de uma ordem específica.

Uma prévia (`Prévia da ordem final`) mostra, em tempo real, a sequência resultante
(`arquivo1 → arquivo2 → arquivo3 → ...`) antes mesmo de clicar em "Unificar Hotfix".

**Por que é uma lista numerada e não "rodar depois de X":** a primeira versão dessa
funcionalidade usava relações par-a-par ("arquivo A depois de arquivo B"), mas isso
permite montar ciclos contraditórios sem nenhum aviso (ex.: A depois de B, B depois de
C, C depois de A — nenhuma ordem linear resolve isso). Uma lista de posições explícitas
elimina esse problema por construção: não existe "ciclo" possível numa sequência 1, 2, 3...

---

## 8. Formato do arquivo gerado

```sql
-- ==== TABELAS (estrutura) ====
-- Hotfix: 001_tabela.sql ----------------------------------------

ALTER TABLE PRODUTOS ADD COLUMN NOVO_CAMPO INTEGER;

-- ==== IMPLEMENTACAO DE PROCEDURES/FUNCTIONS ====
-- Hotfix: 010_calc_total.sp ----------------------------------------

SET TERM ^ ;

CREATE OR ALTER PROCEDURE CALC_TOTAL_PEDIDO (...)
...
^

SET TERM ; ^

-- ==== AJUSTES FINAIS (grants, inserts, updates, etc.) ====
-- Hotfix: 099_grant.sql ----------------------------------------

GRANT EXECUTE ON PROCEDURE CALC_TOTAL_PEDIDO TO PUBLIC;
```

Nenhum comando é reformatado, reindentado ou tem comentários removidos — o único
acréscimo é o cabeçalho `-- Hotfix: ...`, o banner de categoria e, quando necessário,
o `SET TERM`.

---

## 9. Implantação

A aplicação pode ser publicada como um processo Streamlit (`streamlit run src/app.py`)
registrado como uma **Tarefa Agendada do Windows** chamada `HotfixUnifier`, configurada
para:

- Iniciar sozinha no boot do PC, mesmo sem ninguém logado (roda como `SYSTEM`).
- Reiniciar automaticamente até 3 vezes se cair.
- Ficar acessível na rede local pela porta `8501` (liberada no Firewall do Windows).

Assim, qualquer máquina da mesma rede acessa direto pelo navegador em
`http://IP-DA-MAQUINA:8501`, sem precisar instalar nada.

**Gerenciamento (precisa de PowerShell como Administrador):**

```powershell
Get-ScheduledTask -TaskName "HotfixUnifier" | Get-ScheduledTaskInfo   # ver status
Stop-ScheduledTask -TaskName "HotfixUnifier"                          # parar agora
Start-ScheduledTask -TaskName "HotfixUnifier"                         # iniciar agora
Disable-ScheduledTask -TaskName "HotfixUnifier"                       # pausar (não sobe no boot)
Enable-ScheduledTask -TaskName "HotfixUnifier"                        # reativar
```

**Importante:** depois de qualquer alteração no código (`src/app.py`, `src/validator.py`,
`src/merger.py`), é preciso **parar e iniciar a tarefa de novo** para o processo carregar
a versão nova dos arquivos — o Python mantém os módulos em memória e não recarrega
sozinho em produção.

---

## 10. Limitações conhecidas

- **Classificação e versionamento são por arquivo inteiro, não por comando.** Se um
  único arquivo misturar, por exemplo, um `ALTER TABLE` e um `CREATE PROCEDURE` que
  dependa dele, o arquivo inteiro cai em uma única categoria (a de maior prioridade
  encontrada). O ideal é manter o padrão usado na pasta `examples/`: um arquivo por
  objeto/mudança.
- **Extração do nome do objeto pega o primeiro `CREATE/ALTER` do arquivo.** Um arquivo
  com múltiplas procedures em sequência só tem a primeira reconhecida para fins de
  versionamento — as outras duas não seriam substituídas automaticamente se uma nova
  hotfix as redefinisse isoladamente.
- **Conflito entre duas hotfixes novas do mesmo objeto** é resolvido por ordem
  alfabética do nome do arquivo, não por data/hora real — sempre exige conferência
  manual do aviso exibido na tela.
- **Detecção de "stub" (assinatura vazia)** é uma heurística baseada em texto (procura
  `BEGIN`/`END` contendo só `SUSPEND`), não um parser SQL completo. Comentários
  malformados ou estruturas fora do padrão podem confundir a classificação.
- **Detecção de necessidade de `SET TERM`** também é baseada em expressões regulares,
  não em um parser real de SQL/PSQL.
- **Sem histórico, banco de dados ou autenticação** — por definição do escopo do
  projeto. Cada unificação é isolada; o único "estado" entre execuções é o próprio
  arquivo `Hotfix_Unificada.sql` que o usuário decide reenviar ou não.
- **Sem hot-reload em produção** — alterações no código exigem reiniciar a Tarefa
  Agendada manualmente (seção 9).
- **Sem suporte a Docker, filas ou processamento em lote** — é uma aplicação
  single-process, pensada para poucos usuários simultâneos internos.

---

## 11. Stack técnica

| Item | Valor |
|---|---|
| Linguagem | Python 3.12+ (testado com 3.14) |
| Framework | Streamlit |
| Bibliotecas | `streamlit`, `re`, `pathlib` (biblioteca padrão) |
| Banco de dados | Nenhum |
| Autenticação | Nenhuma |
| Contêineres | Não utilizado |
| Hospedagem | Processo local; opcionalmente exposto na rede via Tarefa Agendada do Windows |
