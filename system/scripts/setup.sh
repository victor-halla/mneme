#!/usr/bin/env bash
# Assistente de instalação do Mneme, para uso direto de um checkout ou clone.
#
#   ./system/scripts/setup.sh                    # interativo
#   ./system/scripts/setup.sh --non-interactive --instance-remote <url> ...
#
# Sem terminal interativo, nada é escrito: o script mostra os valores que seriam
# aplicados e o comando exato para aplicar.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${HERE}/brain.py" setup "$@"
