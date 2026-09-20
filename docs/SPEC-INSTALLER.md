# Especificação do instalador por bootstrap

## Objetivo

Um usuário em Linux com Python 3.11+ deve instalar o Mneme com um comando iniciado por `curl`, sem clonar o repositório e sem instalar dependências no Python global.

## Interfaces

```bash
curl -fsSL <url-do-install.sh> | bash
curl -fsSL <url-do-install.sh> | bash -s -- --non-interactive --no-mem0
bash install.sh --archive-url <url-ou-file://> --sha256 <sha256>
```

Variáveis suportadas:

- `MNEME_INSTALL_ROOT`: runtime versionado, padrão `~/.local/share/mneme`.
- `MNEME_BIN_DIR`: diretório da CLI, padrão `~/.local/bin`.
- `MNEME_ROOT`: instância, padrão `~/mneme`.
- `MNEME_REPOSITORY`: repositório público do pacote.
- `MNEME_REF`: ref do arquivo GitHub, padrão `main`.

## Comportamento

1. Validar Bash, Python 3.11+, `venv`, downloader e utilitários de arquivo.
2. Baixar ou ler o artefato em diretório temporário.
3. Validar SHA-256 quando fornecido.
4. Conferir layout e versão do pacote.
5. Criar venv e instalar `requirements.lock`.
6. Promover a release e o symlink `current` atomicamente.
7. Promover CLI e skill por staging.
8. Executar `brain setup --no-install`, usando `/dev/tty` quando interativo.
9. Informar caminhos, versão e aviso de PATH.

## Segurança

- Nunca usar `eval` nem interpolar parâmetros em comandos construídos como texto.
- Recusar versões, refs e checksums com formato inválido.
- Usar `mktemp`, arrays Bash, aspas e `--` antes de caminhos externos.
- Nunca executar conteúdo antes da validação de layout e checksum solicitado.
- Nunca apagar ou substituir a instância de dados.
- Não usar `sudo`.

## Critérios de aceitação

- Instalação limpa produz `current`, `.venv`, `brain` executável e skill completa.
- `brain version` reporta a versão do arquivo `VERSION` instalado.
- Reinstalação remove arquivo obsoleto da skill e preserva a instância.
- Checksum divergente falha antes de criar o destino final.
- Execução por pipe funciona em modo não interativo.
- Sem TTY e sem `--non-interactive`, nenhuma instância é criada.
- A suíte preexistente continua verde.

## Fora de escopo

- Publicação de tag ou GitHub Release.
- Assinatura criptográfica com chave separada.
- `brain self-update`, rollback comandado, doctor completo e uninstall.
- Suporte declarado a macOS ou Windows.
