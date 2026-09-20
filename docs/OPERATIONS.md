# Mneme — operação

## Layout pacote/instância

```text
<checkout do pacote>                     pacote em desenvolvimento
~/.local/share/mneme-package       runtime instalado
~/mneme                            instância de dados
~/mneme/assets/drive               cache local do backend, ignorado pelo Git
~/mneme/.mneme                     índice, estado e fila, ignorados pelo Git
```

O que a instância versiona e o que ela deixa de fora:

| Caminho | Vai para o Git? | Regra |
| --- | --- | --- |
| `entities/`, `projects/`, `areas/`, `knowledge/`, `resources/`, `timeline/`, `inbox/` | sim | — |
| `assets/drive/` | não | `**/assets/drive/` |
| `.mneme/` | não | `.mneme/` |

## Preparação

Configuração assistida: `./system/scripts/setup.sh` resolve os valores que variam por máquina (raiz dos dados, remote Git da instância, backend dos binários no rclone e pasta do Drive), instala runtime, skill e CLI e cria ou adota a instância. Sem terminal interativo ele não escreve nada, apenas mostra o comando para aplicar.

```bash
export PATH="$HOME/.local/bin:$PATH"
export MNEME_ROOT="$HOME/mneme"

# chave do Mem0 (fora do Git, 600)
mkdir -p ~/.config/mneme
printf 'MEM0_API_KEY=%s\n' '<chave>' > ~/.config/mneme/mneme.env
chmod 600 ~/.config/mneme/mneme.env

brain status
```

Inicialização, migração e cache do Drive:

```bash
brain instance init --root ~/mneme \
  --remote <url do repositório de dados> \
  --drive-folder-id <drive-folder-id>
brain instance migrate --source /caminho/legado --root ~/mneme
brain assets check
brain assets sync --dry-run
brain assets sync
```

`assets sync` usa cópia Drive → cache e não apaga arquivos locais. O cache nunca entra no Git.

## Rotina diária

```bash
brain organize                     # consolida o inbox (commits pequenos por item)
brain validate                     # YAML, IDs, relações, segredos, tamanho
brain sync                         # pendências do Mem0 + estado do Git
brain status                       # saúde geral
```

## Registrando conhecimento

```bash
brain remember "Decidimos usar Git como fonte canônica e Mem0 como derivado" --type decision --project mneme
brain remember "Ficou combinado enviar a proposta até sexta" --type commitment --project mneme
brain remember "Ana Souza lidera o programa de IA" --type relationship --entity person-ana-souza
brain remember "guarde isso: o fornecedor X foi aprovado"     # comando explícito aumenta prioridade
```

O comando devolve: classificação, arquivo(s), evento de timeline, commit e estado do Mem0.
Se o Mem0 estiver fora, ele informa `pendente` — nada se perde.

## Consultando

```bash
brain search "orçamento"                     # texto (FTS5)
brain get project-mneme                         # documento canônico
brain history person-ana-souza                  # histórico Git do documento
brain context project-mneme --query "impacto"   # contexto federado, com orçamento de tokens
brain route "se eu alterar processPayment o que quebra?"   # mostra a política de roteamento
```

## Inteligência de código

```bash
brain code list                                  # repositórios indexados
brain code status <projeto-indexado>                # prontidão do índice
brain code search <projeto-indexado> "webhook"      # símbolos
brain code architecture <projeto-indexado>          # visão geral
brain code impact <projeto-indexado> "handleWebhook"  # blast radius (inbound + outbound)
brain code trace <projeto-indexado> "handleWebhook" --direction outbound --depth 3
brain code adr <projeto-indexado> --adr-mode outline
brain code index <caminho do projeto> --name novo-projeto
```

Regra: se o repositório não estiver indexado, indexe antes de perguntar. O grafo é derivado —
nunca é fonte canônica de decisão humana.

## Projetos

```bash
brain project new "Mneme" --code-repo mneme-system=<checkout do pacote>
brain project list
brain project show Mneme
```

## Migração de `~/.hermes`

```bash
brain migrate-hermes scan                     # inventário (somente leitura)
brain migrate-hermes plan                     # destinos propostos
brain migrate-hermes apply --backup --limit 40  # cópia + manifesto (nunca apaga origem)
```

Nada é apagado na origem; segredos são marcados `never_migrate`; o manifesto fica em
`system/manifests/hermes-migration-YYYYMMDD.yaml`.

## Binários e backend remoto (rclone)

O binário nunca entra no Git: o Mneme guarda **metadados e referências** (`resources/`) e o conteúdo
vive no backend remoto. O transporte é o rclone, então qualquer backend suportado por ele serve; o
Google Drive é o padrão. O cache local é `assets/drive`, ignorado pelo Git e descartável.

Fluxo recomendado:

1. instale o rclone e autorize o backend: `rclone config`; no Drive, `rclone config reconnect gdrive:`
   se o token expirar;
2. aponte o backend na configuração da instância: `providers.assets.remote` e, no Drive, `folder_id`;
3. `brain assets check` para conferir binário, remote, tipo, pasta e cache;
4. `brain assets sync --dry-run` para ver o que viria, e só então `brain assets sync`.

O que o comando garante: sem rclone ou sem remote configurado ele falha com erro limpo e instrução,
sem traceback e sem copiar nada; remote do tipo `drive` sem `folder_id` é recusado porque copiaria a
raiz da conta; `folder_id` em backend não-Drive é ignorado com aviso; o cache precisa ser
`assets/drive`, sem symlink e ignorado pelo Git; a cópia nunca apaga, só adiciona e atualiza.

- Status por documento nos índices: `ok` (texto extraído) ou `needs_ocr` (pendente).
- A origem é sempre o backend; nada é enviado de volta, nada sai da máquina.
- Depois de cada sincronização, regenere os arquivos `resources/resource-<titulo>.md` para manter
  a contagem e os status atualizados. Nenhum binário entra no Git.
- Não há pipeline fixo: a extração e o OCR são responsabilidade de quem opera a instalação.

## Fluxo de commit

```text
fetch -> pull --rebase -> escrever -> brain validate -> git add <arquivos explícitos> -> commit -> (push só com autorização)
```

Conflito de rebase: o `store.sync()` aborta o rebase, cria um branch de preservação
(`mneme/conflict-<timestamp>`) e informa — nunca resolve silenciosamente.

## Recuperação de falhas

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| `brain search` não acha algo recém-gravado | índice desatualizado | `brain reindex` |
| `brain validate` com erro de ID duplicado | duas entidades com o mesmo ID | consolide e remova a duplicata |
| `mem0: pendente` | endpoint fora ou chave ausente | `brain sync` depois de corrigir; a fila está em `.mneme/mem0_pending.jsonl` |
| `mem0: desabilitado` | provider desligado no `mneme.yaml` | esperado sem Mem0; para ligar, `brain setup --mem0-host https://api.mem0.ai` |
| `mem0: não enviado (MEM0_API_KEY ausente)` | a plataforma exige credencial e não enfileira | exporte a chave no ambiente e rode `brain sync` |
| `erro: rclone não encontrado` | binário ausente na máquina que sincroniza | `apt install rclone` ou o instalador oficial |
| `erro: remote não configurado: gdrive:` | backend sem OAuth/config | `rclone config`; no Drive, `rclone config reconnect gdrive:` |
| `remote do Google Drive sem ... folder_id` | copiaria a raiz inteira da conta | defina `providers.assets.folder_id` |
| `Failed to create file system ... empty token found` | token do Drive expirado | `rclone config reconnect gdrive:` |
| `folder_id ... ignorado no remote` | backend não é Drive | esperado; remova o `folder_id` ou use um remote do tipo drive |
| `code: unavailable` | binário do provider ausente/erro | valide `brain code health`; o cérebro continua funcionando |
| commit recusado | validação (segredo, YAML, tamanho) | corrija o conteúdo; nada foi escrito |
| projeto não resolvido | projeto inexistente | `brain project new` + `brain organize` |
| `aviso: arquivos já staged ficaram fora deste commit` | havia staged alheio | confira `git diff --cached` e commite (ou descarte) manualmente |
| `caminho escapa da raiz do Mneme` | tentativa de escrever fora do repositório | use sempre caminho relativo à raiz |
| `frontmatter com chave duplicada` | YAML com chave repetida | remova a duplicata (o YAML aceitaria em silêncio) |

## Atualizar a skill no perfil Hermes

A skill `brain-manager` é gerada a partir do repositório (fonte canônica). Sempre que
`skills/brain-manager/` mudar:

```bash
# no host do Hermes (onde ficam os perfis)
./system/scripts/install_skill_remote.sh                        # perfil dev (default)
HERMES_HOME=~/.hermes ./system/scripts/install_skill_remote.sh  # perfil default
```

O script confere o checksum do `SKILL.md` remoto contra o instalado e falha se divergir.
Skills novas exigem sessão nova do Hermes para entrar no contexto.

## Testes

```bash
./system/scripts/run_tests.sh        # unittest (stdlib); a contagem muda com o tempo
python3 -m unittest discover -s system/tests -t system -v -k <padrao>   # um grupo específico
```

Testes que dependem de infraestrutura real (Mem0 e provider de código) se pulam sozinhos quando o
serviço ou a credencial não estão disponíveis; leia o motivo do `skipped` antes de considerar a
validação verde.

Os testes cobrem: núcleo (entidades, projetos, eventos, validação, Git, FTS), Mem0
(real + degradação + retry), code intelligence (real + degradação), migração
(scan/plan/apply/dry-run/secrets), instância (init/migrate, confinamento de caminho,
`~/.mneme` separado do pacote), cache do Drive, roteamento, context compiler e inbox.

## Manutenção automática (opcional, não invasiva)

```bash
hermes cron add --name mneme-maintenance --schedule "0 6 * * *" \
  --prompt "Rode: python3 <checkout do pacote>/system/scripts/brain.py organize; ... validate; ... sync. Relate o resultado."
```

Nunca modifique o core do Hermes para isso: cron + CLI já cobrem a manutenção diária.
