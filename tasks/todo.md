# Tarefas: bootstrap de instalação

- [x] Adicionar `VERSION`, `requirements.lock` e `brain version` com teste primeiro.
- [x] Adicionar testes black-box para instalação por arquivo, pipe, checksum inválido e atualização.
- [x] Implementar `install.sh` com preflight, download, venv e promoção atômica.
- [x] Tornar a atualização da skill substitutiva e cobrir arquivo obsoleto.
- [x] Atualizar documentação e decisão arquitetural.
- [x] Executar validação completa, revisão do diff e varredura de segredos.
- [x] Criar commits atômicos e confirmar estado final.

## Resultado

- Suíte: 145 testes, 145 aprovados, 6 pulados por dependência externa.
- Instalação real por pipe validada em HOME temporário, com CLI, skill, instância e `brain version`.
- Revisão adversarial independente aplicada: layout da skill, imutabilidade de versão, transação,
  concorrência, limites de extração e cadeia de dependência corrigidos.
