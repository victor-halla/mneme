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

O pacote traz um assistente que resolve os três valores que mudam de máquina para máquina: a raiz dos dados, o repositório Git da instância e a pasta raiz do Google Drive.

```bash
./system/scripts/setup.sh        # pergunta um valor por vez, com validação
```

Sem terminal interativo ele não escreve nada: mostra os valores que seriam aplicados e o comando exato para aplicar. Agentes e automação usam o modo sem perguntas:

```bash
./system/scripts/setup.sh --non-interactive \
  --instance-root ~/mneme \
  --instance-remote git@github.com:owner/repo-de-dados.git \
  --drive-folder-id <id-da-pasta-no-drive> \
  --mem0-host http://127.0.0.1:8888 \
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

## Dados confidenciais

Uma instância pode versionar Markdown `confidential` em repositório privado, por decisão explícita do proprietário da instância. Conteúdo `secret`, chaves, tokens, credenciais, índices e caches nunca entram no Git.

O pacote mantém `git.allow_push: false` por padrão. Nenhum push é automático.

## Google Drive

Os binários ficam em `~/mneme/assets/drive/`, caminho ignorado pelo Git. O Drive é a fonte desses arquivos; `resources/` guarda metadados e links versionáveis. O provider precisa de autenticação OAuth do Google na máquina que executar a sincronização.

## Documentação

- `AGENTS.md`: regras para desenvolver o pacote.
- `docs/SPEC-PACKAGE-INSTANCE.md`: contrato da separação pacote/instância.
- `docs/ARCHITECTURE.md`: arquitetura e decisões.
- `docs/OPERATIONS.md`: operação e recuperação.
- `examples/mneme.example.yaml`: configuração de exemplo da instância.

## Licença

MIT. Veja `LICENSE`.
