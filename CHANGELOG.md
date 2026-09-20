# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versão e data por
release; o que ainda não foi publicado fica em `Unreleased`.

## [Unreleased]

Nada pendente de publicação.

## [0.1.0] - 2026-09-20

### Adicionado

- Destino declarado para dado pessoal que não pode ser versionado: `privacy.sensitive_file` no
  `mneme.yaml`, com o `AGENTS.md` da instância explicando as categorias (identificador, contato,
  endereço, saúde, documento), o modo 600 e o fato de o arquivo ser por host. O cérebro guarda o fato e
  a referência; o valor nunca entra no Markdown versionado.
- `brain validate` avisa quando `privacy.sensitive_file` aponta para dentro da instância, porque esse
  arquivo nunca pode ser alcançado por `git add`.
- Bootstrap público `install.sh` para instalação por URL, com Python 3.11+, venv privado, versão ativa
  por symlink, checksum opcional, manifesto por release, limites de extração, `flock` e suporte a
  execução por pipe.
- `brain version`, `brain setup --check`, arquivo canônico `VERSION` e dependência do PyYAML fixada em
  `requirements.lock` com hashes verificados por `pip --require-hashes`.
- `brain setup`: assistente de instalação e configuração, com modo interativo, `--non-interactive`,
  `--dry-run`, adoção de instância existente e instalação de skill para Hermes e Claude Code.
- `brain assets check` e `brain assets sync --dry-run`.
- Dois protocolos de Mem0, cloud e self-hosted, com `providers.mem0.api` declarada ou inferida.
- Cache de binários por rclone em qualquer backend suportado, com `AssetProvider` de rclone
  (`put`, `get`, `metadata`, `delete` e `link` no Drive).
- `--harness` e `--base-dir` no instalador de skill.
- `AGENTS.md` da instância como contrato de instruções entre harnesses.

### Mudado

- Backend de binários padrão passou a ser `provider: rclone` com `remote: gdrive:`, no lugar do
  esboço não implementado da API do Google.
- Mem0 padrão passou a ser a plataforma (`https://api.mem0.ai`), no lugar de servidor local.
- `install_skill.sh` aceita base arbitrária, não só perfil do Hermes.
- Erros do rclone resumidos na linha crítica, sem despejar o log inteiro.
- Documentação reorganizada: decisões, estado do pacote, layout do que é versionado e o que não é.

### Corrigido

- Entidade criada por `brain remember --entity <id>` recebe nome legível derivado do ID estável
  (`person-ana-souza` → `Ana Souza`), em vez de repetir a frase do fato no campo `name`.
- Instalação passou a ser transacional: CLI e skill são preparadas antes da promoção e qualquer falha
  restaura `current`, CLI e skill anteriores.
- Republicação da mesma versão com conteúdo diferente é recusada, em vez de reutilizar silenciosamente
  o runtime antigo.
- Opções inválidas de `brain setup` falham antes de promover runtime, CLI e skill.
- Reinstalação da skill agora substitui a árvore gerenciada e remove arquivos obsoletos.
- O shim da skill resolve o runtime pelo `MNEME_PACKAGE_ROOT`, pelo layout versionado `current` ou pelo
  layout de checkout, em vez de assumir `~/.local/share/mneme-package`.
- CLI instalada a partir do checkout recebe também `VERSION` e reporta a versão corretamente.
- `brain setup --dry-run` no modo texto quebrava com `KeyError: 'instance_root'`, justamente a linha
  documentada no README: a simulação devolve agora a raiz e o caminho da configuração, mostra o
  resumo e não pede confirmação, porque não há o que confirmar quando nada é escrito.
- `assets sync` quebrava com traceback quando o rclone não estava instalado.
- A flag de pasta do Drive era enviada a backends não-Drive, que a ignoravam em silêncio.
- Mem0 desativado ainda tentava a rede e enfileirava pendência.
- Ausência de credencial na plataforma produzia requisição não autenticada e pendência inútil.
- Adoção de instância sobrescrevia host e `user_id` do Mem0 com os padrões do assistente.

### Segurança

- Fixtures de teste sem identificador real: nenhum IP interno, nome de pessoa ou ID de pasta
  verdadeiro no repositório.
