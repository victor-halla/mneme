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
3. Validar SHA-256 quando fornecido e recusar artefato acima dos limites de tamanho, entradas e conteúdo
   descompactado.
4. Conferir layout e versão do pacote.
5. Criar venv e instalar `requirements.lock` com `--require-hashes`.
6. Gravar manifesto da release com o hash do artefato. Versão já instalada só é reutilizada com o mesmo
   hash; conteúdo diferente para a mesma versão é recusado.
7. Preparar CLI e skill em staging.
8. Validar o plano de configuração com `brain setup --check`, sem escrever.
9. Promover `current`, CLI e skill, restaurando os alvos anteriores se qualquer promoção falhar.
10. Executar `brain setup --no-install`, usando `/dev/tty` quando interativo.
11. Informar caminhos, versão, instância efetiva e aviso de PATH.

## Segurança

- Nunca usar `eval` nem interpolar parâmetros em comandos construídos como texto.
- Recusar versões, refs e checksums com formato inválido.
- Usar `mktemp`, arrays Bash, aspas e `--` antes de caminhos externos.
- Nunca executar conteúdo antes da validação de layout e checksum solicitado.
- Adquirir `flock` por raiz de instalação para impedir instaladores concorrentes.
- Limitar download, número de entradas e tamanho descompactado.
- Fixar hashes das dependências com `--require-hashes` e `--no-deps`.
- Nunca apagar ou substituir a instância de dados.
- Não usar `sudo`.

## Critérios de aceitação

- Instalação limpa produz `current`, `.venv`, manifesto, `brain` executável e skill completa.
- `brain version` reporta a versão do arquivo `VERSION` instalado.
- Reinstalação remove arquivo obsoleto da skill e preserva a instância.
- Checksum divergente falha antes de criar o destino final.
- Versão republicada com conteúdo diferente é recusada.
- Falha de promoção restaura `current`, CLI e skill anteriores.
- `file://` funciona sem `curl` instalado.
- Execução por pipe funciona em modo não interativo.
- Sem TTY e sem `--non-interactive`, nenhuma instância é criada.
- A suíte preexistente continua verde.

## Fora de escopo

- Publicação de tag ou GitHub Release.
- Assinatura criptográfica com chave separada.
- `brain self-update`, rollback comandado, doctor completo e uninstall.
- Suporte declarado a macOS ou Windows.
