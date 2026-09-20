# Mneme

Pacote reutilizável para manter uma memória canônica em Markdown/YAML, versionada em Git e compartilhada entre agentes.

Este repositório é o **pacote**: código, schemas, templates, skill e documentação genérica. Ele não guarda dados de nenhuma instância.

O Mneme separa o software da instância de dados:

```text
Pacote Mneme                         Instância Mneme
<caminho do checkout>                ~/mneme
core, CLI, providers, testes         fatos, entidades, projetos, decisões
skills e instaladores                resources, timeline e configuração
        |                                  |
        +---------- brain CLI -------------+
                                           |
                              +------------+-------------+
                              v                          v
                  Repositório Git                  Google Drive
                  Markdown/YAML                    assets/drive/ local
                                                   (ignorado pelo Git)
```

Mem0 é memória semântica derivada. Codebase Memory MCP é inteligência estrutural de código derivada.

## Instalação

O pacote é instalado a partir de um checkout Git:

```bash
git clone https://github.com/victor-halla/mneme.git ~/mneme-src
cd ~/mneme-src
python3 -c "import yaml" || pip3 install --user pyyaml
./system/scripts/run_tests.sh
./system/scripts/install_skill.sh
```

A primeira linha confere a dependência única do pacote, o `PyYAML`. A segunda é opcional e valida o pacote antes de instalar. A terceira instala o runtime, a skill e a CLI.

Para instalar a skill em outro perfil do Hermes, informe o diretório do perfil:

```bash
./system/scripts/install_skill.sh ~/.hermes/profiles/default
```

Para atualizar, atualize o checkout e rode o instalador de novo; a promoção substitui as árvores gerenciadas em vez de mesclar versões:

```bash
git -C ~/mneme-src pull && ~/mneme-src/system/scripts/install_skill.sh
```

Para instalar em outra máquina, que lê o pacote a partir de uma máquina de desenvolvimento por SSH:

```bash
MNEME_SSH=<alias-ssh-do-servidor> \
MNEME_PACKAGE_SOURCE=<caminho do pacote no servidor> \
MNEME_INSTANCE_REMOTE=<url do repositório de dados> \
MNEME_DRIVE_FOLDER_ID=<drive-folder-id> \
./system/scripts/install_skill_remote.sh
```

O instalador separa:

- runtime: `~/.local/share/mneme-package`;
- CLI: `~/.local/bin/brain`;
- dados: `${MNEME_ROOT:-~/mneme}`;
- skill: `${HERMES_HOME:-~/.hermes/profiles/dev}/skills/brain-manager`.

## Configuração assistida

O pacote traz um assistente que resolve os valores que mudam de máquina para máquina: a raiz dos dados, o repositório Git da instância, o backend dos binários no rclone (com a pasta do Drive, quando for Drive), o Mem0 e o perfil que recebe a skill.

```bash
./system/scripts/setup.sh        # pergunta um valor por vez, com validação
```

Sem terminal interativo ele não escreve nada: mostra os valores que seriam aplicados e o comando exato para aplicar. Agentes e automação usam o modo sem perguntas:

```bash
./system/scripts/setup.sh --non-interactive \
  --instance-root ~/mneme \
  --instance-remote git@github.com:USUARIO/mneme-hermes.git \
  --drive-remote "gdrive:" \
  --drive-folder-id <id-da-pasta-no-drive> \
  --mem0-host https://api.mem0.ai \
  --hermes-profile ~/.hermes/profiles/dev

./system/scripts/setup.sh --dry-run        # confere sem escrever
```

Em ordem, ele instala o runtime, a skill e a CLI; consulta o remote da instância e decide entre clonar, quando o remote já tem conteúdo, e inicializar, quando está vazio ou não foi informado; escreve as chaves de configuração; e commita exatamente os arquivos que ele mesmo criou.

Garantias: nunca sobrescreve dados, nunca apaga configuração e nunca faz push. Instância existente é adotada, e só as chaves informadas são alteradas. Remote inacessível falha antes de criar qualquer coisa, em vez de produzir uma instância local que divergiria do repositório.

## Criar ou migrar uma instância

```bash
brain instance init \
  --root ~/mneme \
  --remote <url do repositório de dados> \
  --drive-folder-id <drive-folder-id>

brain instance migrate --source <caminho legado> --root ~/mneme
```

`instance init` cria a árvore, o repositório Git e a configuração, mas não commita `mneme.yaml`, `.gitignore` e `AGENTS.md`. O primeiro commit é seu:

```bash
cd ~/mneme && git add -A && git commit -m "chore: configuração inicial da instância"
```

A migração copia apenas dados canônicos, nunca move ou apaga a origem, recusa colisões e bloqueia padrões de segredo.

## Uso diário

```bash
export MNEME_ROOT="$HOME/mneme"
brain status
brain remember "decidimos usar X por Y"
brain search "orçamento"
brain get project-exemplo
brain context project-exemplo --query "impacto"
brain organize
brain validate
brain reindex
brain sync
```

## Mem0

O Mem0 é memória semântica derivada: o Markdown continua sendo a fonte canônica e o Mem0 é reconstruível a partir dela. O padrão do pacote é o Mem0 cloud:

```yaml
providers:
  mem0:
    enabled: true
    api: platform
    host: https://api.mem0.ai
    user_id: default
    agent_id: mneme
    api_key_env: MEM0_API_KEY
```

Na plataforma a chave vai em `Authorization: Token`, e a instância precisa de `MEM0_API_KEY` no ambiente. Para um servidor OSS próprio (`mem0 serve`), troque o bloco para `api: self-hosted` e `host: http://127.0.0.1:8888`.

Os caminhos diferem por protocolo: `/v3/memories/add/` e `/v3/memories/search/` na plataforma, `/memories` e `/search` no OSS. Sem `api` declarada, o protocolo é inferido pelo host, e host cujo domínio termina em `mem0.ai` é tratado como plataforma.

### Funciona sem o Mem0

Funciona por inteiro, e é uma escolha normal, não um modo degradado. Use `enabled: false` ou `brain setup --no-mem0`. Nesse caso:

- nenhuma rede: nenhuma chamada é tentada e nenhuma pendência é enfileirada;
- `brain remember` grava o Markdown, cria o commit e informa `mem0: desabilitado`;
- `brain search` e `brain context` usam o índice local (SQLite FTS) e a árvore Git;
- `brain status` mostra `Mem0 disabled — n/d` como informação de configuração;
- `brain sync` reporta `0 enviado(s), 0 falha(s), 0 pendente(s)` e segue com o Git.

O que se perde é a busca semântica por similaridade entre sessões e máquinas. O que fica é o cérebro inteiro em texto, versionado.

## Outros harnesses

Os dados não pertencem a nenhum harness: são Markdown e YAML em um repositório Git privado. Qualquer agente que leia arquivos e execute comandos de shell usa esses dados, sem integração específica.

- **CLI e skill**: `./system/scripts/install_skill.sh --harness claude` instala a mesma skill em `~/.claude/skills/brain-manager`, porque o `SKILL.md` segue o padrão aberto Agent Skills, o mesmo do Claude Code. Para qualquer outro harness, `--base-dir <dir>` instala em `<dir>/skills/brain-manager`.
- **Instruções**: a instância traz `AGENTS.md`, o contrato comum entre agentes. O Codex lê esse arquivo direto; o Claude Code usa `CLAUDE.md`, então aponte um para o outro (`ln -s AGENTS.md CLAUDE.md` na raiz da instância) em vez de manter duas cópias.
- **Dados**: clone o repositório privado da instância na máquina do outro harness e exporte `MNEME_ROOT` e `MNEME_PACKAGE_ROOT`. Sem a CLI, os arquivos continuam legíveis e graváveis por qualquer editor; a CLI só organiza, indexa e commita.

```bash
git clone git@github.com:USUARIO/mneme-hermes.git ~/mneme
export MNEME_ROOT="$HOME/mneme"
brain search "orçamento"                  # ou leia knowledge/ direto
brain remember "decidimos X por Y"        # grava, commita e sincroniza
```

## Dados confidenciais

Uma instância pode versionar Markdown `confidential` em repositório privado, por decisão explícita do proprietário da instância. Conteúdo `secret`, chaves, tokens, credenciais, índices e caches nunca entram no Git.

O pacote mantém `git.allow_push: false` por padrão. Nenhum push é automático.

## Binários e backend remoto (rclone)

Binário grande nunca entra no Git: a instância guarda metadados e referências em `resources/`, e o arquivo vive no backend remoto. O transporte é o **rclone**, então vale qualquer backend que ele suporte: Google Drive, S3, WebDAV, OneDrive, Backblaze, um diretório local.

```yaml
providers:
  assets:
    enabled: true
    provider: rclone
    remote: gdrive:          # qualquer remote do rclone; ex.: s3:meu-balde
    folder_id: <id-da-pasta> # só para remote do tipo drive
    cache_dir: assets/drive
```

```bash
brain assets check                   # rclone instalado? remote configurado? tipo? pasta?
brain assets sync --dry-run          # mostra o que seria copiado, sem escrever
brain assets sync                    # copia para assets/drive
brain assets sync --remote s3:balde  # troca o backend só nesta execução
```

O que o comando garante:

- sem rclone instalado, ou com remote não configurado, falha com erro limpo e instrução, sem traceback e sem copiar nada;
- remote do tipo `drive` sem `folder_id` é recusado, porque copiaria a raiz inteira da conta;
- `folder_id` em backend que não é Drive é ignorado, com aviso;
- o cache precisa ser `assets/drive`, sem symlink e ignorado pelo Git;
- `--dry-run` lista os arquivos que seriam copiados e não escreve nada;
- a cópia só adiciona e atualiza, nunca apaga, nem no cache nem no backend.

Para Google Drive, o rclone precisa de OAuth na máquina que sincroniza (`rclone config`; se o token expirar, `rclone config reconnect gdrive:`). O `client_id` compartilhado do rclone está sendo retirado ao longo de 2026, então criar o seu próprio é o caminho durável (https://rclone.org/drive/#making-your-own-client-id).

Se você não usa backend remoto, deixe `enabled: false`: nada é tentado e o resto do Mneme funciona igual.

## Documentação

- `AGENTS.md`: regras para desenvolver o pacote.
- `docs/SPEC-PACKAGE-INSTANCE.md`: contrato da separação pacote/instância.
- `docs/ARCHITECTURE.md`: arquitetura e decisões.
- `docs/OPERATIONS.md`: operação e recuperação.
- `examples/mneme.example.yaml`: configuração de exemplo da instância.

## Licença

MIT. Veja `LICENSE`.
