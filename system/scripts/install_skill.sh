#!/usr/bin/env bash
# Instala/atualiza o runtime Mneme e a skill brain-manager na máquina atual.
#
#   ./install_skill.sh                            # perfil dev do Hermes
#   ./install_skill.sh ~/.hermes/profiles/default # base explícita
#   ./install_skill.sh --harness claude           # ~/.claude (Claude Code)
#   ./install_skill.sh --base-dir <dir>           # qualquer base com skills/
#
# A skill vai para <base>/skills/brain-manager, o runtime para
# $MNEME_PACKAGE_ROOT (~/.local/share/mneme-package) e a CLI para
# $HOME/.local/bin/brain.
set -euo pipefail

BASE_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      case "${2:-}" in
        hermes) BASE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/dev}" ;;
        claude) BASE_DIR="${CLAUDE_HOME:-$HOME/.claude}" ;;
        *)
          echo "harness desconhecido: ${2:-}. Use hermes ou claude, ou informe --base-dir." >&2
          exit 2
          ;;
      esac
      shift 2
      ;;
    --base-dir)
      BASE_DIR="${2:?--base-dir exige um caminho}"
      shift 2
      ;;
    -h|--help)
      echo "uso: install_skill.sh [BASE] [--base-dir DIR] [--harness hermes|claude]"
      exit 0
      ;;
    -*)
      echo "opção desconhecida: $1" >&2
      exit 2
      ;;
    *)
      BASE_DIR="$1"
      shift
      ;;
  esac
done

PACKAGE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL_SRC="${PACKAGE_SRC}/skills/brain-manager"
TARGET_HOME="${BASE_DIR:-${HERMES_HOME:-$HOME/.hermes/profiles/dev}}"
SKILL_TARGET="${TARGET_HOME}/skills/brain-manager"
PACKAGE_TARGET="${MNEME_PACKAGE_ROOT:-$HOME/.local/share/mneme-package}"

if [[ ! -f "${SKILL_SRC}/SKILL.md" ]]; then
  echo "SKILL.md não encontrada em ${SKILL_SRC}" >&2
  exit 1
fi

mkdir -p "$(dirname "${SKILL_TARGET}")" "${PACKAGE_TARGET}/system" "$HOME/.local/bin"
skill_stage="$(mktemp -d "$(dirname "${SKILL_TARGET}")/.brain-manager.XXXXXXXX")"
cp -a "${SKILL_SRC}/." "${skill_stage}/"
skill_backup=""
if [[ -e "${SKILL_TARGET}" ]]; then
  skill_backup="$(dirname "${SKILL_TARGET}")/.brain-manager.backup.$$"
  mv -- "${SKILL_TARGET}" "${skill_backup}"
fi
if ! mv -- "${skill_stage}" "${SKILL_TARGET}"; then
  [[ -n "${skill_backup}" ]] && mv -- "${skill_backup}" "${SKILL_TARGET}"
  echo "não foi possível promover a skill" >&2
  exit 1
fi
[[ -n "${skill_backup}" ]] && rm -rf -- "${skill_backup}"
cp -f "${PACKAGE_SRC}/VERSION" "${PACKAGE_SRC}/requirements.lock" "${PACKAGE_TARGET}/"
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
