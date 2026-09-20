---
id: resource-exemplo
type: resource
name: Nome do arquivo
aliases: []
tags: []
relations: []
created: 2026-09-19
updated: 2026-09-19
sensitivity: private
provider: rclone
file_id: null
mime_type: application/pdf
size: null
sha256: null
---

# Nome do arquivo

## Metadados

- provider: rclone | local
- file_id:
- mime_type:
- size:
- sha256:

## Uso

por que este arquivo importa, quem precisa dele e com que frequência

O binário NUNCA vai para o Git: só estes metadados e a referência no backend. O caminho no backend é o
que o `rclone` usa para buscar o arquivo, e é ele que `brain assets sync` traz para `assets/drive/`
(`system/providers/assets.py`).
