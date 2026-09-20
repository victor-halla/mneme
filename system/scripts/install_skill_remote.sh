#!/usr/bin/env bash
# Instala/atualiza o runtime Mneme e a skill brain-manager no host do Hermes.
# Este script roda NO HOST DO HERMES e lê o pacote no servidor de desenvolvimento.
#
#   ./install_skill_remote.sh
#   MNEME_INSTANCE_REMOTE=https://github.com/owner/private-repo ./install_skill_remote.sh
set -euo pipefail

SSH_HOST="${MNEME_SSH:-dev-server}"
REMOTE_PACKAGE="${MNEME_PACKAGE_SOURCE:?defina MNEME_PACKAGE_SOURCE com o caminho do pacote na maquina de desenvolvimento}"
TARGET_HOME="${HERMES_HOME:-$HOME/.hermes/profiles/dev}"
SKILL_TARGET="${TARGET_HOME}/skills/brain-manager"
PACKAGE_TARGET="${MNEME_PACKAGE_ROOT:-$HOME/.local/share/mneme-package}"
INSTANCE_ROOT="${MNEME_ROOT:-$HOME/mneme}"
INSTANCE_REMOTE="${MNEME_INSTANCE_REMOTE:-}"
DRIVE_FOLDER_ID="${MNEME_DRIVE_FOLDER_ID:-}"

# Endereço SSH nunca pode ser lido como opção do ssh (ex.: -oProxyCommand=...).
if [[ -z "${SSH_HOST}" || "${SSH_HOST}" == -* || "${SSH_HOST}" == *" "* ]]; then
  echo "ERRO: MNEME_SSH inválido" >&2
  exit 1
fi

# Caminhos vão como argumentos posicionais: sem interpolação em shell remoto.
remote_tar() {
  local -a sources=("$@")
  ssh -- "${SSH_HOST}" tar czf - -C "${REMOTE_PACKAGE}" -- "${sources[@]}"
}

remote_sha() {
  ssh -- "${SSH_HOST}" sha256sum -- "$1" | awk '{print $1}'
}

staging="$(mktemp -d)"
trap 'rm -rf "${staging}"' EXIT

mkdir -p "${staging}/skill" "${staging}/package" "$HOME/.local/bin"

remote_tar skills/brain-manager | tar xzf - --strip-components=2 -C "${staging}/skill"
remote_tar VERSION requirements.lock system/core system/providers system/adapters system/scripts system/schemas system/templates \
  | tar xzf - -C "${staging}/package"

# Promoção: substitui as árvores gerenciadas em vez de mesclar versões.
rm -rf "${SKILL_TARGET}" "${PACKAGE_TARGET}"
mkdir -p "${SKILL_TARGET}" "${PACKAGE_TARGET}"
cp -a "${staging}/skill/." "${SKILL_TARGET}/"
cp -a "${staging}/package/." "${PACKAGE_TARGET}/"
printf '%s\n' "${PACKAGE_TARGET}" > "${SKILL_TARGET}/scripts/.package-root"

chmod +x "${SKILL_TARGET}"/scripts/* "${PACKAGE_TARGET}"/system/scripts/* 2>/dev/null || true
cp -f "${SKILL_TARGET}/scripts/brain" "$HOME/.local/bin/brain"
chmod 700 "$HOME/.local/bin/brain"

remote_hash="$(remote_sha "${REMOTE_PACKAGE}/skills/brain-manager/SKILL.md")"
local_hash="$(sha256sum "${SKILL_TARGET}/SKILL.md" | awk '{print $1}')"
if [[ "${remote_hash}" != "${local_hash}" ]]; then
  echo "ERRO: checksum da skill divergente" >&2
  exit 1
fi

if [[ ! -e "${INSTANCE_ROOT}" && -n "${INSTANCE_REMOTE}" ]]; then
  git clone "${INSTANCE_REMOTE}" "${INSTANCE_ROOT}"
fi
if [[ ! -f "${INSTANCE_ROOT}/mneme.yaml" ]]; then
  init_args=(instance init --root "${INSTANCE_ROOT}")
  [[ -n "${INSTANCE_REMOTE}" ]] && init_args+=(--remote "${INSTANCE_REMOTE}")
  [[ -n "${DRIVE_FOLDER_ID}" ]] && init_args+=(--drive-folder-id "${DRIVE_FOLDER_ID}")
  "$HOME/.local/bin/brain" "${init_args[@]}"
fi

echo "runtime      : ${PACKAGE_TARGET}"
echo "skill        : ${SKILL_TARGET}"
echo "brain        : $HOME/.local/bin/brain"
echo "instância    : ${INSTANCE_ROOT}"
echo "checksum     : ${local_hash}"
