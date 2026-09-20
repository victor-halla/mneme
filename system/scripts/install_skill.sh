#!/usr/bin/env bash
# Instala/atualiza o runtime Mneme e a skill brain-manager na máquina atual.
# Uso: ./install_skill.sh [HERMES_HOME]
set -euo pipefail

PACKAGE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL_SRC="${PACKAGE_SRC}/skills/brain-manager"
TARGET_HOME="${1:-${HERMES_HOME:-$HOME/.hermes/profiles/dev}}"
SKILL_TARGET="${TARGET_HOME}/skills/brain-manager"
PACKAGE_TARGET="${MNEME_PACKAGE_ROOT:-$HOME/.local/share/mneme-package}"

if [[ ! -f "${SKILL_SRC}/SKILL.md" ]]; then
  echo "SKILL.md não encontrada em ${SKILL_SRC}" >&2
  exit 1
fi

mkdir -p "${SKILL_TARGET}/scripts" "${SKILL_TARGET}/schemas" \
  "${PACKAGE_TARGET}/system" "$HOME/.local/bin"
cp -f "${SKILL_SRC}/SKILL.md" "${SKILL_TARGET}/SKILL.md"
cp -f "${SKILL_SRC}"/schemas/*.json "${SKILL_TARGET}/schemas/" 2>/dev/null || true
cp -f "${SKILL_SRC}"/scripts/* "${SKILL_TARGET}/scripts/" 2>/dev/null || true
for directory in core providers adapters scripts schemas templates; do
  rm -rf "${PACKAGE_TARGET}/system/${directory}"
  cp -a "${PACKAGE_SRC}/system/${directory}" "${PACKAGE_TARGET}/system/${directory}"
done
chmod +x "${SKILL_TARGET}"/scripts/* "${PACKAGE_TARGET}"/system/scripts/* 2>/dev/null || true
cp -f "${SKILL_TARGET}/scripts/brain" "$HOME/.local/bin/brain"
chmod 700 "$HOME/.local/bin/brain"

echo "runtime Mneme instalado em ${PACKAGE_TARGET}"
echo "brain-manager instalada em ${SKILL_TARGET}"
echo "CLI instalada em $HOME/.local/bin/brain"
