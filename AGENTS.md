# Mneme — arquitetura e regras para agentes

Este é o repositório do **pacote Mneme**: o código reutilizável, os schemas, os templates e a skill.
Os dados canônicos (fatos, entidades, projetos, decisões, timeline) vivem na **instância**, em repositório
separado, por padrão em `~/mneme`. Este arquivo é lido por qualquer agente (Hermes, Claude Code, Codex,
Cursor) que trabalhe aqui.

## O que é este repositório

Mneme é um cérebro em Markdown/YAML versionado em Git. A instância guarda fatos, entidades, projetos,
decisões, timeline, conhecimento e metadados de recursos. Tudo é texto, tudo é auditável. Este repositório
guarda o software que opera esse cérebro.

`system/core` é o core (Python 3.11, stdlib + PyYAML). `system/providers` são integrações com serviços
externos. `system/scripts/brain.py` é a CLI. `skills/brain-manager/` é a skill que o agente carrega.

## Princípio central

```text
Mneme / Git / Markdown  = fonte canônica de fatos, entidades, projetos, timeline,
                          decisões, conhecimento e metadados de recursos.
Mem0                    = memória semântica DERIVADA, condensada para recuperação rápida.
Codebase Memory MCP     = inteligência estrutural de código (símbolos, chamadas, impacto,
                          arquitetura). Nunca é fonte canônica de decisão humana.
Backend remoto (rclone) = armazenamento de binários grandes; só metadados no Git.
Agente                  = um dos clientes que raciocina e executa sobre essas fontes.
```

## Regras obrigatórias

1. Nenhum dado de instância entra neste repositório: aqui só vivem código, schemas, templates, skill e
   documentação genérica. Nada de dados pessoais, caminhos privados, IDs de documentos ou endereços internos.
2. `~/.hermes` é runtime/configuração do harness. **Nunca** é base canônica de conhecimento.
3. Conhecimento persistente vive na instância, fora de `~/.hermes` e fora deste repositório.
4. Git/Markdown é a fonte canônica. Mem0 e Codebase Memory são derivados.
5. Não reimplemente Mem0 (busca semântica) nem Codebase Memory (inteligência de código).
6. O SQLite FTS do Mneme indexa `.md`/`.yaml` do cérebro. **Não** indexe código-fonte.
7. Sincronização principal: `Git/Markdown -> Mem0`.
8. Nunca commite segredos (`.env`, chaves, tokens, credenciais, caches de sessão). Sensibilidade
   `secret` significa **nunca commitar**. Dado pessoal que não é versionável (identificador, contato,
   endereço, saúde, documento) também não entra aqui: o valor vive no arquivo local declarado em
   `privacy.sensitive_file` da instância, fora do Git; o cérebro guarda o fato e a referência.
9. Todo estado gerado fica em `.mneme/` dentro da instância (ignorado pelo Git; só dados reconstruíveis).
10. Nunca `git add .`. Sempre arquivos explícitos. Nunca `git push` sem autorização.
11. Migrações seguem `scan -> plan -> apply`, com backup e sem apagar originais.
12. Cada entidade tem ID estável (`tipo-slug`). Nunca use o caminho do arquivo como identidade.
13. Antes de criar, procure: `brain search`, `brain get`, `brain context`.

## Fluxo de escrita (padrão)

```text
classificar -> resolver entidade -> escrever Markdown -> validar (brain validate)
-> commit pequeno e semântico -> sincronizar Mem0 (derivado)
```

Se o Mem0 estiver indisponível: o Git continua válido, o pendente é registrado em
`.mneme/mem0_pending.jsonl` e o `brain sync` reprocessa depois.

## Estrutura

Este pacote:

```text
system/                core, providers, adapters, scripts, schemas, templates e testes
skills/brain-manager/  skill que o agente carrega
docs/                  arquitetura, operação e contrato pacote/instância
examples/              configuração de exemplo da instância
```

A instância, fora daqui:

```text
~/mneme/
  mneme.yaml
  inbox/            entradas não classificadas (YYYYMMDD-HHMMSS-slug.md)
  entities/         people organizations places things animals
  projects/         <Nome do Projeto>/{project.md,AGENTS.md,tasks.md,decisions.md,.brain.yaml,...}
  areas/            responsabilidades contínuas
  timeline/         YYYY/MM/YYYY-MM-DD.md (eventos do mundo/projeto, não histórico técnico)
  knowledge/        notes/ topics/
  resources/        metadados de arquivos grandes (o binário fica no backend remoto)
  assets/drive/     cache local do backend (rclone), ignorado pelo Git
  .mneme/           índices e estado derivado, ignorados pelo Git
```

Git history = histórico técnico. Timeline = acontecimentos. Não misture os dois.

## Comandos

Use a CLI (na raiz do checkout, ou `brain` depois de instalar):

```bash
python3 system/scripts/brain.py status
python3 system/scripts/brain.py search "orçamento"
python3 system/scripts/brain.py context project-exemplo
python3 system/scripts/brain.py remember "decidimos X" --type decision
python3 system/scripts/brain.py validate
python3 system/scripts/brain.py code impact <projeto> <simbolo>
python3 system/scripts/brain.py assets check
python3 system/scripts/brain.py version
./system/scripts/setup.sh              # instala runtime, skill e CLI, e cria ou adota a instância
./install.sh --help                    # bootstrap público, sem checkout permanente
```

Sempre que uma pergunta envolver estrutura de código, o caminho é o provider de code
intelligence (`brain code ...`), nunca grep manual nem indexação de código no FTS.

## Contribuição

Ao alterar `skills/brain-manager/`, reinstale com `./system/scripts/install_skill.sh <base>` (o perfil
do Hermes por padrão, `--harness claude` para o Claude Code, `--base-dir` para qualquer destino).
`install_skill_remote.sh` continua válido para instalar a partir de uma máquina de desenvolvimento, via
SSH, conferindo o checksum do `SKILL.md`. Mudou o core (`system/core`, `system/providers`)? Rode a
suíte: `./system/scripts/run_tests.sh`. Antes de abrir mudança, confirme que nenhum dado de instância,
caminho privado ou identificador pessoal entrou em arquivo versionado, testes incluídos.
