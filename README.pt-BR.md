<div align="center">

<img src="assets/banner.svg" alt="devin-memory" width="100%"/>

<a href="https://github.com/Icaro0310/devin-memory/actions/workflows/ci.yml"><img src="https://github.com/Icaro0310/devin-memory/actions/workflows/ci.yml/badge.svg" alt="ci"/></a>
<a href="https://scorecard.dev/viewer/?uri=github.com/Icaro0310/devin-memory"><img src="https://api.scorecard.dev/projects/github.com/Icaro0310/devin-memory/badge" alt="OpenSSF Scorecard"/></a>
<a href="https://m8ven.ai/mcp/icaro0310/devin-memory?s=readme"><img src="https://m8ven.ai/badge/mcp/icaro0310/devin-memory" alt="M8ven Score"/></a>

</div>

# devin-memory

> **Projeto comunitário não oficial.** Sem afiliação, endosso ou patrocínio
> da Cognition AI. "Devin" é marca registrada da Cognition AI.

**[English](README.md)** · Português (BR)

Um armazenamento de memória anti-envenenamento para o Devin: fatos duráveis
com proveniência, versionamento e uma fila de quarentena — para que a
memória do agente não seja corrompida silenciosamente por uma sessão ruim
ou por conteúdo injetado.

## O problema

Memória de agente é um vetor de envenenamento. Qualquer ferramenta que
persiste "fatos" entre sessões pode ser corrompida por uma única sessão
ruim — uma instrução injetada ou um segredo colado vira uma crença
confiável em todas as sessões futuras, sem etapa de revisão e sem como
responder *"de onde isso veio?"*.

## Trabalhos anteriores

- O **MCP de memória do Devin** (`retain`/`recall`/`reflect` sobre
  `.devin/memory/memories.jsonl`) — só anexa, sem triagem e sem
  proveniência de sessão. O `devin-memory` exporta exatamente nesse
  formato de linha.
- **MemGPT / memória do LangChain** — camadas de persistência otimizadas
  para relembrar, não para auditar ou desconfiar do que foi guardado.

O `devin-memory` adapta a ideia de armazenamento de memória; ele adiciona
as partes que essas ferramentas não têm: um portão de quarentena e
proveniência até linhas reais de sessão.

## O que o torna nativo do Devin

1. **Lado a lado:** cada entrada pode carregar `source_session_id` +
   `source_rowid`, auditáveis contra o `sessions.db` do Devin via o
   armazenamento somente-leitura do `devin-internals` — o MCP de memória
   não consegue verificar se uma sessão de origem alegada (ou uma linha
   de mensagem específica) realmente existiu. O portão de quarentena
   também tria cada escrita em busca de formatos de segredo e de injeção.
2. **Sem Devin:** sem `sessions.db` não há proveniência de sessão para
   auditar — o extra desaparece.
3. **Em uma frase:** *é um armazenamento de memória que lembra de onde
   cada memória veio — e põe em quarentena as suspeitas até um humano
   liberá-las.*

## Instalação

É necessário Python ≥ 3.10 e `pipx`. **Windows (PowerShell):** instale o
`pipx` com `py -m pip install --user pipx`, rode `py -m pipx ensurepath` e
reabra o terminal. **Linux (Debian/Ubuntu):** rode
`sudo apt install pipx python3-venv` e `pipx ensurepath`; reabra o
terminal. Outras distribuições devem instalar o `pipx` pelo gerenciador
de pacotes.

```bash
pipx install "devin-memory @ git+https://github.com/Icaro0310/devin-memory.git"
```

Para desenvolvimento:

```bash
pip install -e ".[dev]"
pytest
```

## Uso

```bash
# Guardar um fato (triado na escrita; conteúdo suspeito vai para quarentena)
devin-memory retain "CI verde no Windows + Linux" --tags ci,status
devin-memory retain "..." --source-session <session-id> --source-rowid <n>
devin-memory retain "..." --workspace /caminho/do/projeto  # escopo de workspace

# Recall com ranking por palavra-chave — só devolve entradas ativas
devin-memory recall "ci status" [--json] [--limit 5] [--tags a,b]

# Fila de quarentena: listar, marcar uma entrada existente ou liberar
devin-memory quarantine                          # lista com motivos
devin-memory quarantine <id> [--reason manual:x] # marca entrada como quarentenada
devin-memory quarantine --release <id>           # override humano -> ativa

# Contradições: um retain conflitante é vinculado, não sobrescrito
devin-memory conflicts [--json]     # pares (nova, antiga); resolva com
                                    # supersede / retract / quarantine <id>

# Minerar uma sessão em busca de conhecimento durável -> entradas
# "proposed" (inativas até revisão); extração é heurística — ver
# "Limitações"
devin-memory extract <session-id> --sessions-db caminho/para/sessions.db
devin-memory extract --latest --sessions-db caminho/para/sessions.db [--auto-approve]
devin-memory list --status proposed   # fila de revisão
devin-memory approve <id>             # proposed -> ativa

# Bloco de contexto para um hook UserPromptSubmit — só entradas ativas,
# filtradas por workspace + perfil da máquina, limitado a ~4 chars/token
devin-memory prime [--workspace PATH] [--max-tokens N]

# Versionamento e manutenção
devin-memory supersede <id> "fato corrigido"
devin-memory retract <id>
devin-memory list [--status active|proposed|quarantined|retracted] [--json]

# Auditar a proveniência de uma entrada contra um sessions.db real
# (somente leitura)
devin-memory verify <id> --sessions-db caminho/para/sessions.db

# Exportar memórias ativas para um JSONL compatível com o MCP de memória
devin-memory export --out memories.jsonl
```

## Servidor MCP

<!-- mcp-name: io.github.icaro0310/devin-memory -->

O `devin-memory` também é um servidor MCP de verdade (stdio) — o mesmo
pipeline retain/recall com a trava de quarentena em cada escrita,
chamável do Devin, Claude Desktop, Cursor ou qualquer cliente MCP:

```bash
pipx install "devin-memory[mcp] @ git+https://github.com/Icaro0310/devin-memory.git"
```

Configuração do cliente:

```json
{
  "mcpServers": {
    "devin-memory": {
      "command": "devin-memory-mcp",
      "args": ["--db", "/caminho/para/memory.db"]
    }
  }
}
```

Tools: `retain`, `recall`, `screen` (teste seco da trava, sem escrita),
`list`, `retract`, `supersede`, `quarantine`, `release`, `approve`,
`conflicts`, `prime`, `verify`, `extract`. Toda tool devolve dados
estruturados ou um objeto `{"error", "detail"}` — nada sobe pelo
transporte. `DEVIN_MEMORY_DB` funciona como alternativa a `--db`.

## Aprenda com sessões usando o `devin-learning`

Esta CLI companheira extrai lições candidatas de um `sessions.db` e escreve
rascunhos de skills revisáveis. Por padrão não instala rascunhos em um
workspace.

```bash
devin-learning extract --sessions-db caminho/para/sessions.db --out ./learning-drafts
devin-learning review --out ./learning-drafts

# Depois de revisar os rascunhos, permita explicitamente a saída para um
# diretório de skills ativo:
devin-learning extract --sessions-db caminho/para/sessions.db --out .devin/skills --apply
```

`review` é um dry-run a menos que `--apply` seja passado; `review --apply`
move rascunhos rejeitados para `_rejected/`. O extrator lê o conteúdo das
sessões, então mantenha a saída privada até revisar.

## Estados da memória

`active` · `proposed` (extraída, aguardando `approve`) · `quarantined`
(triada ou marcada manualmente, aguardando `release`) · `retracted`
(retirada ou substituída). Apenas entradas `active` aparecem em
`recall`/`prime`/`export` — conteúdo em quarentena nunca é impresso nem
recuperado.

## Conflitos, extração e prime (heurísticas)

- **Conflitos** — um `retain` que dá a diretiva oposta sobre o mesmo
  assunto normalizado de uma entrada ativa existente é guardado ao lado
  dela com um vínculo `conflicts_with` (`devin-memory conflicts`). A
  heurística compara uma "chave de assunto" sem stop-words mais a
  polaridade afirmativa/proibitiva — ela deliberadamente perde
  contradições reformuladas em vez de vincular fatos sem relação.
- **`extract`** varre os `message_nodes` de uma sessão (somente leitura
  via devin-internals) em busca de sinais de conhecimento durável —
  correções do usuário ("na verdade", "actually", "the right way"),
  preferências ("always", "never", "sempre", "nunca"), comandos
  descobertos (ferramentas conhecidas entre crases) e caminhos.
  Candidatos passam pela mesma triagem de qualquer escrita: os limpos
  viram `proposed`, os suspeitos `quarantined`. `--auto-approve` pula a
  etapa de revisão.
- **`prime`** emite um bloco compacto
  `# devin-memory: recalled context (heuristic)` dimensionado para um
  hook de prompt. Entradas com escopo de `retain --workspace` só aparecem
  dentro daquele workspace; entradas escritas sob outro perfil de máquina
  nunca aparecem (o perfil tem padrão `corporate` — falha fechada).

O armazenamento é `./memory.db` por padrão — sobrescreva com `--db` ou
`DEVIN_MEMORY_DB`. É o único armazenamento em que esta ferramenta escreve;
`sessions.db`, `acp-messages/*.db` e `state.vscdb` do Devin são apenas
lidos.

## Funciona só com o Devin (modo Devin-only)

O devin-memory mantém um armazenamento local de memória com rastreamento
de proveniência e uma fila de quarentena — sem serviço de memória externo,
sem chamadas de rede. Ambos os scripts de console (`devin-memory` e
`devin-learning`) rodam apenas na sua máquina.

Ressalva honesta: a triagem na escrita é uma heurística, não uma garantia —
entradas suspeitas vão para a quarentena para **revisão humana**, então
mantenha esse hábito.

## Suporte de plataforma

O armazenamento de memória usa um caminho SQLite local explícito e o banco
de sessões é informado com `--sessions-db`; nenhum caminho específico de
plataforma é assumido. Windows e Linux são suportados e cobertos por CI.

## Limitações

- **A extração é heurística e propõe por padrão.** `extract` levanta
  frases com sinais de palavra-chave de uma sessão para uma fila de
  revisão `proposed` — nada fica ativo sem `approve` (ou
  `--auto-approve`). Para um pipeline de lições mais rico, veja o
  `devin-learning`.
- **A triagem é um filtro, não uma garantia.** Detecção de segredos por
  padrões e heurísticas de injeção têm falsos positivos (→ quarentena, um
  comando para liberar) e falsos negativos. Rode scanners dedicados
  (gitleaks, `devin-redact`) também — isto os complementa.
- **O ranking do recall é por palavra-chave**, determinístico e
  documentado — sem embeddings nem busca semântica.
- **A proveniência é registrada, não auto-verificável.** `retain` guarda
  o `source_session_id`/`source_rowid` alegado; `verify` o audita depois
  contra um `sessions.db` real. Um ator mal-intencionado pode alegar
  proveniência falsa — o ponto é que ela é *verificável*.
- **Substituições em quarentena ainda aposentam a versão antiga.** Se a
  substituta for para quarentena, revise a fila (`quarantine --release`).
- **Ainda não está no PyPI** — instale a partir do repositório por ora.

## Quando usar

- Você persiste memória de agente entre sessões e quer desconfiança por
  padrão: toda escrita triada, entradas suspeitas em quarentena para
  liberação humana.
- Você precisa responder "de onde veio esta memória?" — entradas carregam
  `source_session_id`/`source_rowid`, auditáveis via `verify`.
- Você quer versionamento de memória — `supersede`/`retract` mantêm
  histórico em vez de edições silenciosas.
- Você quer injetar contexto lembrado no prompt — `prime` emite um bloco
  compacto e limitado para um hook `UserPromptSubmit`.
- Você quer manter compatibilidade: `export` escreve o formato de linha
  `memories.jsonl` do MCP de memória do Devin.

## Quando NÃO usar

- Você precisa de recall semântico — o ranking é por palavra-chave, sem
  embeddings.
- Você espera que a triagem capture tudo — é um filtro heurístico; rode
  scanners dedicados (gitleaks, devin-redact) em paralelo.
- Você espera que o `extract` leia intenção — ele casa sinais de
  palavra-chave e propõe por padrão justamente porque heurísticas erram.

## FAQ

**Como evito que a memória do agente seja envenenada por uma sessão ruim?**
Use `devin-memory retain` em vez de anexar a um armazenamento bruto. Toda
escrita é triada em busca de formatos de segredo e injeção — entradas
suspeitas vão para a quarentena e só ficam ativas depois que um humano
roda `quarantine --release <id>`.

**O devin-memory prova que uma memória veio de uma sessão real?** Sim, via
proveniência registrada. `retain --source-session <id> --source-rowid <n>`
guarda a origem alegada, e `devin-memory verify <id> --sessions-db
<caminho>` a audita em modo somente-leitura contra o `sessions.db` real do
Devin — uma origem fabricada é verificável, não confiada cegamente.

**O devin-memory substitui o MCP de memória do Devin?** Ele o complementa.
O MCP só anexa, sem triagem; o devin-memory adiciona quarentena,
proveniência e versionamento, e `devin-memory export --out memories.jsonl`
produz exatamente o formato de linha que o MCP lê.

## Licença

MIT — veja [LICENSE](LICENSE).
