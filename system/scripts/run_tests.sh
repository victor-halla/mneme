#!/usr/bin/env bash
# Roda a suíte de testes do Mneme (unittest, stdlib — sem pytest no servidor de dev).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
python3 -m unittest discover -s system/tests -t system -v "${@}"
