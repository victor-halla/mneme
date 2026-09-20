---
name: brain-manager
description: "Use when remembering, organizing or auditing persistent knowledge (Mneme): save facts/decisions, search the brain, compile project context, query code intelligence, migrate ~/.hermes. Triggers: guarde isso, salve no cérebro, lembre disso, organize o que conversamos, o que sabemos sobre X, por que decidimos isso, quem chama esta função, impacto de alterar X, brain status."
---

# brain-manager — memória persistente do usuário (Mneme)

O Mneme separa **pacote** e **instância**:

- o pacote reutilizável contém core, CLI e skill. O bootstrap instala em
  `~/.local/share/mneme/releases/<versão>` com `current` apontando para a versão ativa; o instalador de
  checkout usa `~/.local/share/mneme-package`. O shim desta skill resolve o runtime pelo
  `MNEME_PACKAGE_ROOT`, pelo arquivo `.package-root` gravado ao lado dele ou pelos layouts padrão;
- a instância de dados fica em **`~/mneme`** por padrão (`MNEME_ROOT` pode alterar);
- no host Hermes, a instância esperada é `~/mneme`;
- cada backend remoto possui seu próprio clone e compartilha dados pelo Git privado.

A instância é a **fonte canônica** de fatos, entidades, projetos, decisões, timeline e metadados
de recursos. Mem0 é memória semântica **derivada**. Codebase Memory MCP é inteligência
estrutural de código **derivada**. Binários do backend remoto (rclone) ficam no cache local `assets/drive/`,
ignorado pelo Git.

CLI, após a instalação:

```bash
brain status
```

## Quando usar cada coisa

| Pedido do usuário | Ação |
| --- | --- |
| "guarde isso", "salve no meu cérebro", "lembre disso" | `brain remember "<texto>"` |
| "não precisa guardar", "isso é temporário" | não grave nada (política de memória) |
| "o que sabemos sobre X?" | `brain search "X"` + `brain get <id>` (+ Mem0 pela memória do perfil) |
| "salve que <entidade> tem/é/faz <fato>" | fato: `brain remember "<fato>" --entity <id>` criando ou atualizando a entidade |
| "onde estamos no projeto X?" | `brain context project-x --query "status"` |
| "o que aconteceu ontem/semana passada" | `brain context timeline` ou leia `timeline/YYYY/MM/` |
| "organize o que conversamos hoje" | `brain remember` para os fatos + `brain organize` |
| "quem chama esta função", "estrutura do repo" | `brain code search/architecture <projeto> ...` |
| "qual o impacto de alterar X" | `brain code impact <projeto> <símbolo>` |
| "por que isso foi feito assim" | `brain context` (decisões) + `brain code adr <projeto>` + `git log` |
| "como está o cérebro/memória" | `brain status` |

Consulta obrigatória antes de criar: **procure antes** (`brain search`, `brain get`,
`brain context`). Nunca crie duplicata: se existe, atualize (append com data).

Fato sobre uma pessoa, organização, lugar, coisa ou animal: resolva primeiro a **entidade** por ID
estável `tipo-slug` (ex.: `person-nome-sobrenome`, `thing-nome-do-objeto`), criando o arquivo em
`entities/` quando ainda não existir, e grave o fato com `brain remember "<fato>" --entity <id>`.
As `relations` do frontmatter apontam para IDs que já existem, nunca para texto solto nem para
caminho de arquivo. Se o fato citar outra entidade, use o ID dela.

## Fluxo de escrita (nunca pule etapas)

```text
1. classificar        (o brain faz: decisão? compromisso? relação? evento? nota?)
2. resolver entidade  (ID estável tipo-slug; nunca caminho de arquivo como identidade)
3. escrever Markdown  (na pasta correta: knowledge/, projects/, entities/, timeline/)
4. validar            (brain validate — YAML, IDs, relações, segredos, tamanho)
5. commit pequeno     (só arquivos explícitos; nunca git add .)
6. sincronizar Mem0   (derivado; se falhar, fica pendente e o brain sync reprocessa)
```

`brain remember` executa esse fluxo inteiro. Prefira ele a editar arquivos à mão.
Para edição manual (refinar um project.md, por exemplo), depois de editar rode
`brain validate` e `brain reindex`, e faça um commit pequeno.

## Regras duras

1. `~/.hermes` é runtime do harness, **nunca** base canônica de conhecimento.
2. Nunca versione segredos: `.env`, chaves, tokens, credenciais, caches de sessão.
   Sensibilidade `secret` = nunca commitar. Se o texto parecer credencial, **não grave**.
   Dado que não vai ao Git (identificador, contato, endereço, saúde, documento) não é descartado e
   não é gravado no repositório: vira **fato no cérebro + valor no arquivo restrito** indicado por
   `privacy.sensitive_file` no `mneme.yaml`, fora da instância, fora de `~/.hermes` e com modo 600.
   O cérebro guarda o fato e a referência; **nunca o valor**.
3. Nunca `git add .`; nunca `git push` sem autorização explícita do proprietário.
4. Não indexe código-fonte no FTS do Mneme: para código use `brain code ...`.
5. Não reimplemente Mem0 (busca semântica) nem Codebase Memory (grafo de código).
6. Git history = histórico técnico. Timeline = acontecimentos. Não misture.
7. Migração de `~/.hermes` só em `scan -> plan -> apply`, copiando (nunca apagando origem).
8. Se um provider estiver fora, degrade com honestidade: o canônico continua valendo e a
   pendência fica registrada.

## Dado pessoal que não vai ao Git

Identificador (CPF, RG, CNH, CNS, PIS, título de eleitor, registro de classe, passaporte), contato,
endereço, saúde e documento nunca entram no Markdown versionado, nem em repositório privado. O
procedimento é sempre o mesmo: **fato no cérebro, valor no arquivo restrito**.

```bash
# 1. o valor vai para o arquivo local, fora da instância e fora de ~/.hermes
sensitive="$(sed -n 's/^[[:space:]]*sensitive_file:[[:space:]]*//p' "$MNEME_ROOT/mneme.yaml")"
sensitive="${sensitive/#\~/$HOME}"
mkdir -p "$(dirname "$sensitive")" && chmod 700 "$(dirname "$sensitive")"
printf '%s\n' "<id-da-entidade> | <categoria> | <valor>" >> "$sensitive"
chmod 600 "$sensitive"

# 2. o fato e a referência vão para o cérebro, sem o valor
brain remember "<entidade> informou <categoria>; valor no arquivo restrito declarado em privacy.sensitive_file" \
  --entity <id-da-entidade>
```

Regras de execução:

- o valor nunca aparece no texto do `brain remember`, no commit, no Mem0 nem na resposta ao usuário;
- o arquivo é por host: não é sincronizado pelo Git e não deve ser copiado entre máquinas;
- `~/.hermes` é runtime do harness; gravar em pasta privada do harness **não** é destino válido;
- se a categoria for `secret` (chave, token, senha), não grave nem no arquivo restrito: recuse e
  informe onde a credencial deve ficar.

## Consultando Mem0 e o grafo de código

- **Mem0 (semântico)**: use as tools `mem0_search` / `mem0_add` do próprio Hermes para
  memória de conversa. Para o Mneme gravar memória derivada, `brain remember` já sincroniza.
  O provider fala dois protocolos, escolhidos por `providers.mem0.api` ou inferidos pelo host: cloud
  (`https://api.mem0.ai`, `/v3/memories/add/` e `/v3/memories/search/`, `Authorization: Token`) e
  self-hosted (`/memories` e `/search`, `X-API-Key`). A chave vem de `MEM0_API_KEY` no ambiente, nunca
  do Git nem do chat; com `enabled: false` o Mneme funciona inteiro, sem rede.
- **Codebase Memory**: `brain code list` mostra os repositórios indexados. Sempre resolva o
  nome do projeto indexado (ex.: `<repositório indexado>` → `<projeto-indexado>`). Se um repositório
  não estiver indexado, `brain code index <caminho>`. Use `brain code impact` para blast
  radius, `brain code search` para símbolos, `brain code architecture` para visão geral.
  Grep continua válido para trecho exato.

## Como responder ao usuário (procedência)

Ao responder algo que veio do cérebro, cite a origem: **memória canônica (Mneme/Git)**,
**Mem0 (derivada)** ou **code intelligence (Codebase Memory, derivada)**. Exemplo:

> Segundo as decisões registradas no Mneme (`projects/Mneme/decisions.md`), ... .
> A análise de impacto vem do grafo (Codebase Memory): ...

Nunca apresente uma memória derivada do Mem0 como se fosse decisão canônica.

## Referência rápida de comandos

```bash
brain status                                   # estado da instância e providers
brain instance init --root ~/mneme             # cria uma instância separada do pacote
brain instance migrate --source /caminho/antigo --root ~/mneme  # copia dados, nunca move
brain remember "decidimos X por Y"             # classifica, grava, valida, commita, sincroniza
brain remember "guarde isso: ..." --force      # comando explícito de guardar
brain search "orçamento"                    # busca textual (SQLite FTS)
brain get person-joao-silva                    # lê o documento canônico
brain history person-joao-silva                # histórico Git do documento
brain context project-mneme --query "impacto"  # contexto federado com orçamento
brain organize                                 # classifica e consolida o inbox
brain validate                                 # antes de qualquer commit manual
brain reindex                                  # índice incremental
brain sync                                     # pendências do Mem0 + sync do Git
brain project new "Nome do Projeto" --code-repo id=/caminho
brain code list | status | search | architecture | impact | trace | adr
brain migrate-hermes scan|plan|apply           # migração segura de ~/.hermes
```

## Hooks e manutenção (Fase 24)

- **after_message**: candidatos a memória viram `brain remember` (sem ruído: só decisão,
  compromisso, relação, mudança de projeto, evento importante, preferência relevante).
- **after_session**: consolide decisões/tarefas/eventos da sessão e rode `brain organize`.
- **after_git_commit**: só o conteúdo alterado vai para o Mem0 (`brain sync`).
- **after_code_change**: não reindexe código à mão — verifique se o provider percebeu
  (`brain code status <projeto>`).
- **daily_maintenance**: `brain organize`, `brain validate`, `brain sync`, checagem de
  health do Mem0 e do Codebase Memory, verificação das codebases configuradas.

Se precisar automatizar, use cron não invasivo (`hermes cron add`) em vez de modificar o core.

## Armadilhas conhecidas

1. Projeto não resolvido → o texto vai para `inbox/` com aviso. Resolva criando o projeto
   (`brain project new`) e rodando `brain organize`.
2. ID duplicado quebra `brain validate`; corrija antes de commitar (o commit é recusado).
3. Conteúdo que "parece senha" nunca é gravado — é comportamento correto, não bug.
4. O índice FTS é derivado: se a busca não achar algo recém-criado, rode `brain reindex`.
5. `brain code` depende do binário no servidor; se estiver ausente, `health` diz
   `unavailable` e as operações de cérebro continuam funcionando.
6. `mneme.yaml` configura a instância; `.mneme/` é reconstruível e nunca é versionado.
7. Pacote e dados são independentes: `MNEME_PACKAGE_ROOT` localiza o runtime e `MNEME_ROOT`
   localiza o clone de dados. Nunca grave dados no checkout do pacote.
8. `brain instance migrate` recusa o conjunto inteiro se qualquer arquivo falhar no preflight
   (segredo, `sensitivity: secret`, YAML inválido, colisão ou symlink no destino). Bloqueio não é
   bug: corrija a origem ou use `--overwrite` conscientemente.
9. A instância contém dados pessoais e é sincronizada com repositório privado. Push só com
   autorização explícita do proprietário; nunca torne o repositório público nem adicione colaborador
   externo sem essa autorização.
10. `brain assets check` antes de sincronizar, e `brain assets sync` exige `cache_dir: assets/drive` ignorado pelo Git; o cache é cópia local do
    Drive e não entra no histórico.
11. O Mem0 tem dois protocolos: cloud (`https://api.mem0.ai`, `/v3/memories/add/` e `/v3/memories/search/`,
   `Authorization: Token`) e self-hosted (`/memories` e `/search`, `X-API-Key`). Em ambos a busca exige as
   entidades dentro de `filters`; sem isso a API devolve 400. O provider injeta `user_id` — não chame a API cru.
12. `trace_path` do Codebase Memory exige qualified name. Use `brain code impact <projeto> <alvo>`
   com nome curto: o provider resolve (`GitMemoryStore` → a classe; `remember` → o método) e, se o
   MCP responder `ambiguous`, ele segue a primeira sugestão.
13. Diretórios fora do índice (`.gitignore`, `docs/`, `system/scripts/` em alguns repos) não geram
   arestas de chamada: "quem chama isso" pode vir vazio **sem** ser bug. Confirme com
   `brain code status <projeto>` e, se precisar, reindexe com `--mode full`.
14. Cada host tem o seu grafo: o MCP do perfil `dev` roda no servidor de dev; o MCP local do host
    Hermes é outro índice. Consulta estrutural de `<servidor>/...` só vale no servidor.
15. Contexto sempre cita procedência (`[mneme]`, `[timeline]`, `[mem0]`, `[code-intelligence]`).
    Ao responder o usuário, mantenha essa distinção — memória derivada não é decisão canônica.
16. Commit tem escopo: `git commit -- <paths>` commita **só** o autorizado. O aviso "arquivos já
    staged ficaram fora deste commit" é proteção contra arrastar segredo, não erro.
17. Escrita só dentro da raiz: caminho absoluto, `..`, `~` e travessia por symlink são recusados;
    nome de projeto com separador é inválido. Arquivos 0600, diretórios 0700 — não afrouxe.
18. Achados de revisão independente (GPT-5.6-sol) e riscos residuais estão em
    `docs/ARCHITECTURE.md` § Endurecimento; regressões em `system/tests/test_hardening.py`.
19. Um clone do repositório de dados materializa arquivos conforme o umask local (o Git só guarda o
    bit executável). Em máquina compartilhada, clone com `umask 077`.
20. Gravar dado pessoal em pasta privada do harness (`~/.hermes/...`) é destino errado: aquilo é
    runtime, não é base de conhecimento e não segue a política de retenção nem o backup do cérebro. O
    destino é o arquivo declarado em `privacy.sensitive_file`.
21. O arquivo de dados sensíveis é por host e não viaja no Git. Antes de responder sobre um
    identificador, verifique se ele existe **neste** host; se não existir, diga que o valor está no
    outro host em vez de inventar ou deduzir o número.
