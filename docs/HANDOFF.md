# Estado do pacote

Documento de continuidade do desenvolvimento do pacote. Aqui entra só o estado do software: sem dado
de instância, sem caminho privado e sem identificador pessoal.

## Pronto e verificado

- CLI `brain` com `instance`, `setup`, `assets`, `status`, `search`, `get`, `remember`, `context`,
  `history`, `diff`, `validate`, `reindex`, `organize`, `sync`, `route`, `classify`, `project`,
  `code` e `migrate-hermes`.
- Instância como repositório Git próprio, com `.gitignore` que exclui `.mneme/`, `assets/drive/`,
  segredos e ruído local.
- Mem0 em dois protocolos, opcional, com fila de pendências e degradação sem rede.
- Binários por rclone em qualquer backend, com `check`, `sync` e `--dry-run`.
- Assistente de instalação interativo e com `--non-interactive`, que adota instância existente sem
  sobrescrever configuração, e `--dry-run` para conferir.
- Bootstrap público `install.sh`, compatível com `curl | bash`, Python 3.11+, venv privado com
  `--require-hashes`, checksum opcional, limites de extração, `flock`, manifesto por release, promoção
  transacional com rollback e substituição integral da skill.
- `brain version` e `brain setup --check`; versão canônica em `VERSION`, dependência fixada em
  `requirements.lock`.
- Instalação da skill para Hermes e para Claude Code.
- Suíte cobrindo raiz, instância, migração, mem0, assets, setup e endurecimento.

## Pendente, com dono

- **`folder_id` do backend confirmado por quem opera**: a sincronização real depende de um único ID
  de pasta, confirmado contra o que está registrado nos índices de recursos. Enquanto houver dúvida,
  `brain assets check` acusa e `sync` fica em `--dry-run`.
- **OAuth do backend na máquina que sincroniza**: `rclone config`; no Drive, `rclone config
  reconnect`. O `client_id` compartilhado do rclone está sendo retirado ao longo de 2026, então criar
  o próprio é o caminho durável.
- **Sincronização de ponta a ponta com um Drive real**: validada com backend local; com Drive real
  depende dos dois itens acima.
- **Uso dentro de Claude Code e Codex**: o alvo de instalação e o formato da skill estão prontos e
  testados; falta abrir cada harness e confirmar.
- **Primeira tag e release pública**: o bootstrap funciona contra archive de branch, tag ou URL explícita,
  mas ainda falta publicar uma release imutável e seu SHA-256. Publicação e push exigem autorização.

## Riscos conhecidos

- Versões publicadas são imutáveis por contrato do instalador: corrigir uma release exige nova versão.
- `--dry-run` do `setup` valida o plano e a configuração, mas não sonda o destino nem o remote: um
  destino não vazio ou um remote inacessível só aparecem na aplicação real. A simulação diz o que
  seria feito, não garante que daria certo.
- Mem0 em HTTP sem TLS fora do loopback: aceitável só em rede confiável, e o `health()` avisa.
- Sem lock entre operações concorrentes: dois `remember` simultâneos podem disputar o mesmo arquivo.
- Janela TOCTOU entre validar e gravar caminho; risco baixo em ambiente de usuário único.
- `gitleaks` é opcional e o scanner interno é heurístico.

## Como conferir antes de publicar mudança

```bash
./system/scripts/run_tests.sh        # suíte completa
python3 -m compileall -q system      # sintaxe do runtime
grep -rniE 'IP-interno|nome-de-pessoa|id-de-pasta-real' . | grep -v '^./.git/'   # varredura antes do push
```
