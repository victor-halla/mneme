# Plano: bootstrap de instalação do Mneme

## Objetivo

Permitir instalar o Mneme a partir de uma única URL, sem checkout Git permanente e sem modificar o Python do sistema. O bootstrap deve baixar um pacote, validar sua integridade quando um checksum esperado for fornecido, criar um ambiente virtual, promover o runtime de forma atômica, instalar CLI e skill e então reutilizar `brain setup` para criar ou adotar a instância.

## Decisões

- O bootstrap público será `install.sh`, autocontido e compatível com `curl ... | bash`.
- Python mínimo: 3.11. O PyYAML será instalado em `.venv` próprio, fixado por `requirements.lock`.
- Releases instaladas ficam em `${MNEME_INSTALL_ROOT:-~/.local/share/mneme}/releases/<versão>` e `current` é um symlink promovido atomicamente.
- O wrapper `~/.local/bin/brain` aponta para `current` e para o Python do venv.
- A skill é promovida por staging, substituindo integralmente a árvore gerenciada.
- A instância `${MNEME_ROOT:-~/mneme}` nunca é removida nem substituída pelo bootstrap.
- O modo interativo usa `/dev/tty`; sem TTY, o bootstrap exige `--non-interactive`.
- Para testes e distribuição controlada, `--archive-url` e `--sha256` permitem fornecer artefato e checksum explícitos.

## Fases

1. Adicionar `VERSION`, dependência fixada e `brain version`.
2. Criar testes black-box do bootstrap e observar falhas.
3. Implementar download, checksum, venv, promoção atômica, CLI, skill e chamada ao setup.
4. Corrigir promoção da skill no instalador de checkout para remover arquivos obsoletos.
5. Atualizar README, decisões, changelog e handoff.
6. Executar suíte, sintaxe, instalação local por arquivo e por pipe, revisão de segurança e diff.

## Riscos e mitigação

| Risco | Mitigação |
| --- | --- |
| Download adulterado | HTTPS e `--sha256`; releases devem publicar checksum do artefato |
| Interrupção durante update | preparar em staging e trocar `current` somente após instalação válida |
| `curl | bash` sem stdin interativo | reabrir `/dev/tty`; falhar de forma segura quando indisponível |
| Perda de dados | runtime e instância permanecem em árvores distintas; bootstrap nunca apaga a instância |
| PyYAML incompatível com sistema | venv privado com versão fixada |
| Arquivos antigos na skill | substituir a árvore inteira via staging |

## Verificação

- `./system/scripts/run_tests.sh`
- `python3 -m compileall -q system`
- `bash -n install.sh system/scripts/*.sh system/scripts/brain skills/brain-manager/scripts/brain`
- instalação black-box em HOME temporário dentro de `/srv/dev`
- execução via pipe e em modo não interativo
- `brain version` e `brain status` usando o runtime instalado
