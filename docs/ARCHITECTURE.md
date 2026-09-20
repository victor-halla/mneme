# Mneme — arquitetura

## Separação pacote/instância

```text
<checkout do pacote>                     código reutilizável do pacote
~/.local/share/mneme-package       runtime instalado em cada host
~/mneme                            clone Git da instância de dados
~/mneme/assets/drive               cache local do Drive, ignorado pelo Git
```

O pacote nunca é a raiz implícita dos dados. A CLI resolve a instância por `--root`,
`MNEME_ROOT` ou `~/mneme`, nesta ordem. Cada backend remoto possui seu próprio clone; GitHub
sincroniza Markdown/YAML e Google Drive sincroniza os binários. Isso evita misturar releases do
software com fatos pessoais e permite instalar a mesma versão do pacote em vários agentes.

## Visão geral

```text
Hermes (perfil dev)  /  OpenClaw  /  Claude Code  /  Codex  /  Cursor
                              |
                       brain-manager (skill)
                              |
                      Context Compiler (core/context_compiler.py)
                              |
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
      Mneme                 Mem0          Codebase Memory MCP
  Git / Markdown      memória semântica      grafo de código
  (CANÔNICO)            (DERIVADO)              (DERIVADO)
        |
        v
      GitHub (fase seguinte)

  Recursos grandes -> AssetProvider -> Google Drive (fase seguinte)
```

## Camadas e responsabilidades

| Camada | Onde | Papel | Pode ser fonte de verdade? |
| --- | --- | --- | --- |
| Mneme (Git/Markdown) | `~/mneme` por instalação | fatos, entidades, projetos, decisões, timeline, conhecimento, metadados | **Sim, é a única canônica** |
| Pacote Mneme | checkout de desenvolvimento ou `~/.local/share/mneme-package` | core, CLI, providers, skill e testes | não contém a instância canônica |
| Mem0 | `http://<host-do-mem0>:8888` | recuperação semântica rápida de memórias condensadas | não (derivado) |
| Codebase Memory MCP | binário no servidor de dev | símbolos, chamadas, arquitetura, impacto, ADRs técnicos | não (derivado) |
| AssetProvider | `system/providers/assets.py` | binários grandes (Google Drive, fase seguinte) | não (só metadados no Git) |
| Hermes | `~/.hermes` | runtime/harness que opera tudo | **nunca** |

## Core (`system/core`)

| Módulo | Responsabilidade |
| --- | --- |
| `config.py` | raiz, `mneme.yaml`, segredos por ambiente (`~/.config/mneme/mneme.env`, 600) |
| `models.py` | IDs estáveis (`tipo-slug`), tipos, sensibilidade, frontmatter YAML |
| `store.py` | `GitMemoryStore`: get/write/history/diff/commit/sync/push(bloqueado)/snapshot |
| `validate.py` | YAML, IDs únicos, relações, datas, tamanho, scanner de segredos (+gitleaks) |
| `classify.py` | classificação determinística de texto + política de memória |
| `projects.py` | criação de projetos (unidade de contexto) e `.brain.yaml` |
| `timeline.py` | `timeline/YYYY/MM/YYYY-MM-DD.md` e IDs `event-YYYYMMDD-NNNN` |
| `index.py` | SQLite FTS5 incremental (só Markdown/YAML do cérebro) |
| `routing.py` | política de roteamento: quais fontes consultar para cada pergunta |
| `context_compiler.py` | federação das fontes + orçamento de tokens + procedência |
| `organize.py` | consolidação do inbox, com detecção de duplicatas |
| `migrate_hermes.py` | inventário/plano/execução da migração de `~/.hermes` |
| `actions.py` | camada de serviço (`Brain`) que o CLI e os harnesses usam |

Providers (`system/providers`): `Mem0Provider`, `CodebaseMemoryProvider`, `assets.py`.
Adapters (`system/adapters`): `HermesAdapter` (detecta home/perfil/skills/hooks/cron) e
`GenericAdapter`. A dependência aponta **sempre do adapter para o core**, nunca o contrário.

## Decisões de arquitetura

1. **Markdown/Git é a fonte canônica.** Mem0 e Codebase Memory são derivados reconstruíveis.
2. **Nada de reimplementar providers.** O Mneme traduz chamadas; não recria busca semântica
   nem análise de código.
3. **FTS5 do Mneme indexa apenas `.md`/`.yaml` do cérebro.** Código-fonte é do provider.
4. **`.mneme/` da instância nunca é versionado** (índice FTS, contadores, fila de pendências).
5. **Skills permanecem no harness** durante a migração: elas são memória procedural do
   runtime, não fatos do cérebro. A migração copia conhecimento/projetos, nunca o runtime.
6. **`~/.hermes` nunca é base canônica** (regra 1 do plano).
7. **Push é bloqueado por padrão** (`git.allow_push: false` + `push.default=nothing` no servidor).
8. **Degradação elegante**: sem Mem0, o Git continua válido e a pendência é enfileirada; sem o
   binário do Codebase Memory, o cérebro segue operando e o provider reporta `unavailable`.
9. **Procedência explícita no contexto**: cada seção compilada carrega `[mneme]`, `[mem0]`,
   `[timeline]` ou `[code-intelligence]`.
10. **Projeto é a unidade de contexto**: `project.md`, `decisions.md`, `tasks.md`, `.brain.yaml`.

## Segurança

- Tipos de sensibilidade: `public`, `internal`, `private`, `confidential`, `secret`.
- `secret` = **nunca commitar**; o `remember` recusa gravar texto que pareça credencial.
- `brain validate` roda scanner interno e usa `gitleaks` quando instalado.
- A chave do Mem0 vive no ambiente (`MEM0_API_KEY`), carregada de arquivo 600 fora do repositório.
- Nunca `git add .`; nunca `git push` sem autorização explícita do proprietário.

## Endurecimento após revisão independente (19/09/2026)

Dois revisores independentes (GPT-5.6-sol, família diferente do modelo que escreveu o código)
auditaram a V2 com foco em correção e segurança. Todos os achados abaixo foram **confirmados por
procedimento próprio** antes da correção e estão cobertos por testes de regressão em
`system/tests/test_hardening.py`.

| # | Achado | Gravidade | Correção |
| --- | --- | --- | --- |
| 1 | `commit` arrastava arquivos já staged (inclusive segredo detectado) | alto | commit usa a forma com pathspec (`git commit -- <paths>`): só os caminhos autorizados entram; staged alheio fica de fora e é reportado |
| 2 | Caminhos escapavam da raiz (`../`, absoluto, symlink) e `project new ../../x` gravava fora | alto | `safe_relpath()` central (recusa absoluto, `..`, `~`, travessia por symlink) + validação de nome de projeto |
| 3 | Migração sobrescrevia destino homônimo e reportava ambos como copiados | alto | destino único por origem (sufixo derivado do caminho) + flag `collision` no manifest |
| 4 | Exclusão do inbox (duplicata) não era commitada, deixando a árvore suja | médio | `commit` aceita exclusões de arquivos versionados; `organize` commita a remoção |
| 5 | Arquivos privados criados como 0644/diretorios 0755 | médio | arquivos 0600, diretórios 0700 (criação e restrição do pai imediato) |
| 6 | Scanner com falsos negativos (github_pat_, telegram 13 dígitos, senha com espaço) e falso positivo | alto | novos padrões + heurística de senha com entropia + ordem específica antes da genérica |
| 7 | Chave do Mem0 podia ser refletida no erro e persistida na fila | alto | erro sanitizado (`_redact` remove chave/headers) e corpo HTTP nunca persistido |
| 8 | Chave YAML duplicada aceita em silêncio | baixo | `StrictLoader` na validação: chave duplicada é erro |
| 9 | Escrita composta deixava estado parcial quando a segunda gravação falhava | médio | `write_many()`: prepara todos os temporários e só então promove com `os.replace` |

Riscos residuais aceitos e documentados:

- **Mem0 em HTTP sem TLS** dentro de uma rede interna; `health()` agora emite aviso
  quando o host não é loopback. Migrar para TLS antes de qualquer exposição fora da rede.
- **Sem lock entre operações concorrentes**: dois `brain remember` simultâneos podem disputar o
  mesmo arquivo. Uso atual é serial; se houver concorrência, introduzir lock de arquivo.
- **Janela TOCTOU** entre validar e gravar caminho (symlink trocado no meio). Risco baixo em
  ambiente de usuário único; mitigação definitiva exigiria `openat`/`O_NOFOLLOW`.
- **`gitleaks` opcional**: o gate usa o scanner interno quando o binário não está instalado, e o
  scanner interno é heurístico.

## Preparação multi-harness

O core não conhece harness. Para adicionar OpenClaw, Claude Code, Codex, Cursor ou um cliente
MCP genérico, basta um adapter em `system/adapters/` ou um servidor MCP que exponha a CLI
(`brain ...`). A persistência distribuída (sessões vinculadas a escopos, Fase 22) é declarada
em `.brain.yaml` (`sessions:`), usando **IDs estáveis**, nunca nomes visuais de sessão.
