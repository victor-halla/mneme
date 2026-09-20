# Spec: separar pacote Mneme da instância de dados

## Objetivo

Manter o código reutilizável do Mneme em um checkout de desenvolvimento e armazenar os dados de cada
instalação em um repositório separado, por padrão `~/mneme`. Cada instalação aponta para o seu próprio
repositório de dados, privado quando o conteúdo for confidencial.

## Decisões aprovadas

- O checkout do pacote é a fonte do software, não a raiz dos dados de ninguém.
- Cada instalação usa `MNEME_ROOT`, com padrão `~/mneme`.
- Uma instância pode versionar Markdown classificado como `confidential`, por decisão explícita do
  proprietário da instância.
- Conteúdo `secret`, credenciais, tokens, caches, índices e estado derivado nunca entram no Git.
- Binários ficam em `assets/drive/` dentro da instância, ignorados pelo Git e sincronizados separadamente.
- O `folder_id` do Drive é definido por instalação e registrado na configuração dela.
- Nenhum push será feito sem autorização explícita separada.

## Estrutura

### Pacote

```text
<checkout>/
  system/                 core, providers, adapters, scripts, schemas, templates e testes
  skills/brain-manager/   integração com agentes
  docs/                   arquitetura, operação e este contrato
  examples/               configuração de exemplo da instância
```

### Instância

```text
~/mneme/
  .git/
  mneme.yaml
  AGENTS.md
  inbox/
  entities/
  projects/
  areas/
  knowledge/
  resources/
  timeline/
  assets/drive/           cache local, ignorado pelo Git
  .mneme/                 índices e estado derivado, ignorados pelo Git
```

## Comandos

```bash
python3 system/scripts/brain.py instance init --root ~/mneme --remote <url>
python3 system/scripts/brain.py instance migrate --source <origem legada> --root ~/mneme
MNEME_ROOT=~/mneme python3 system/scripts/brain.py status
./system/scripts/run_tests.sh
```

## Comportamento

1. `find_root()` respeita raiz explícita, depois `MNEME_ROOT`, depois `~/mneme`; a árvore do pacote só é usada quando passada explicitamente.
2. `instance init` cria uma instância segura, inicializa Git quando necessário e nunca sobrescreve arquivos existentes sem opção explícita.
3. `instance migrate` copia apenas dados canônicos da fonte para a instância, preserva originais e detecta colisões.
4. A instância usa `.mneme/` para FTS, estado e fila do Mem0.
5. `assets/drive/` existe localmente, mas é ignorado pelo Git.
6. A configuração registra o Drive como provider e o `folder_id` aprovado por instalação.
7. Instaladores e skill não fixam o caminho do checkout do pacote como raiz de dados.

## Testes

- Resolução da raiz com prioridade correta.
- Inicialização da estrutura e regras de `.gitignore`.
- Recusa de sobrescrita e de destinos inseguros.
- Migração por cópia, incluindo colisão e preservação da origem.
- Ausência de `assets/drive`, `.mneme`, segredos e caches no conjunto versionável.
- Suíte existente sem regressões.

## Limites

Sempre:
- preservar os dados de origem;
- usar repositório Git privado quando a instância tiver conteúdo confidencial;
- validar e escanear segredos antes de commit/push.

Perguntar antes:
- push para GitHub;
- remoção de dados legados de qualquer árvore;
- compartilhamento ou mudança de permissões no Drive.

Nunca:
- versionar `assets/drive/`, credenciais ou conteúdo `secret`;
- apagar a origem durante a migração;
- usar `git push --force`.

## Critérios de sucesso

- Uma instância temporária pode ser inicializada e migrada sem depender da árvore do pacote como raiz de dados.
- O comando `status` opera sobre essa instância.
- O repositório de dados pode ser preparado localmente com o remote escolhido, sem push.
- O pacote não contém dado de instância, caminho privado nem identificador pessoal.
- Testes, validação e revisão de segredos passam.
