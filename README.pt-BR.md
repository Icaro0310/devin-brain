# devin-memory

> **Projeto comunitário não oficial.** Sem afiliação, endosso ou patrocínio da
> Cognition AI. "Devin" é marca registada da Cognition AI.

**[English](README.md)** · Português (BR)

Um armazenamento de memória anti-envenenamento para o Devin: factos duráveis
com proveniência, versionamento e um portão de quarentena — para que a
memória do agente não possa ser corrompida silenciosamente por uma sessão
má ou por conteúdo injetado.

## O problema

A memória do agente é um vetor de envenenamento. Qualquer ferramenta que
persista "factos" entre sessões pode ser corrompida por uma única sessão má
— uma instrução injetada ou um segredo colado torna-se uma crença confiável
em todas as sessões futuras, sem revisão e sem forma de responder *"de onde
isto veio?"*.

## Trabalho anterior (prior art)

- O **memory MCP do Devin** (`retain`/`recall`/`reflect` sobre
  `.devin/memory/memories.jsonl`) — append-only, sem triagem, sem
  proveniência de sessão. O `devin-memory` exporta exatamente esse formato.
- **MemGPT / memória do LangChain** — camadas de persistência otimizadas
  para recall, não para auditar ou desconfiar do que foi gravado.

O `devin-memory` adapta a ideia de memory store; adiciona as partes que
essas ferramentas não têm: um portão de quarentena e proveniência até às
linhas reais da sessão.

## O que o torna Devin-native

1. **Lado a lado:** cada entrada pode carregar `source_session_id` +
   `source_rowid`, auditável contra o `sessions.db` do Devin via store
   read-only do `devin-internals` — o memory MCP não consegue verificar que
   a sessão (ou a linha de mensagem) alegada alguma vez existiu. O portão
   de quarentena também tria cada escrita para formas de segredo e de
   injeção.
2. **Sem Devin:** sem `sessions.db` não há proveniência de sessão para
   auditar — o extra desaparece.
3. **Uma frase:** *é uma memória que lembra de onde cada memória veio — e
   põe as suspeitas em quarentena até um humano as libertar.*

## Instalação

```bash
pipx install devin-memory
```

Para desenvolvimento:

```bash
pip install -e ".[dev]"
pytest
```

## Uso

```bash
# Guardar um facto (triado na escrita; conteúdo suspeito vai para quarentena)
devin-memory retain "CI verde em Windows + Linux" --tags ci,status
devin-memory retain "..." --source-session <session-id> --source-rowid <n>

# Recall com ranking por keywords — devolve apenas entradas ativas
devin-memory recall "ci status" [--json] [--limit 5] [--tags a,b]

# Rever e libertar entradas em quarentena
devin-memory quarantine                 # lista com razões
devin-memory quarantine --release <id>  # override humano -> active

# Versionamento e manutenção
devin-memory supersede <id> "facto corrigido"
devin-memory retract <id>
devin-memory list [--status active|quarantined|retracted] [--json]

# Auditar a proveniência de uma entrada contra um sessions.db (read-only)
devin-memory verify <id> --sessions-db caminho/para/sessions.db

# Exportar memórias ativas para JSONL compatível com o memory MCP
devin-memory export --out memories.jsonl
```

A base de dados é `./memory.db` por defeito — muda com `--db` ou
`DEVIN_MEMORY_DB`. É o único store em que esta ferramenta escreve; o
`sessions.db`, `acp-messages/*.db` e `state.vscdb` do Devin são apenas
lidos, nunca modificados.

## Limitações

- **M1 é uma primitiva — ainda não há extração automática.** `retain`
  guarda o que lhe é dito; transformar sessões em memórias é M2 (pipeline
  `devin-learning`).
- **A triagem é um filtro, não uma garantia.** Deteção de segredos por
  padrões e heurísticas de injeção têm falsos positivos (→ quarentena, um
  comando para libertar) e falsos negativos. Corre também scanners
  dedicados (gitleaks, `devin-redact`) — isto complementa-os.
- **O ranking do recall é por keywords**, determinístico e documentado —
  sem embeddings nem pesquisa semântica no M1.
- **Proveniência é registada, não auto-verificada.** `retain` guarda o
  `source_session_id`/`source_rowid` alegado; `verify` audita-o contra um
  `sessions.db` real depois. Um mau ator pode alegar proveniência falsa —
  a diferença é que é *verificável*.
- **Supersessões em quarentena reformam a versão antiga na mesma.** Se a
  substituição ficar em quarentena, revê a fila (`quarantine --release`).
- **Ainda não está no PyPI** — instala a partir do repositório por agora.

## Licença

MIT — vê [LICENSE](LICENSE).
