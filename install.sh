#!/usr/bin/env bash
# Bootstrap público do Mneme. Baixa e instala o pacote sem alterar o Python do sistema.
set -euo pipefail

REPOSITORY="${MNEME_REPOSITORY:-victor-halla/mneme}"
REF="${MNEME_REF:-main}"
ARCHIVE_URL="${MNEME_ARCHIVE_URL:-}"
EXPECTED_SHA256="${MNEME_SHA256:-}"
INSTALL_ROOT="${MNEME_INSTALL_ROOT:-$HOME/.local/share/mneme}"
BIN_DIR="${MNEME_BIN_DIR:-$HOME/.local/bin}"
PYTHON="${MNEME_PYTHON:-python3}"
INTERACTIVE=true
HARNESS="hermes"
SKILLS_BASE=""
HERMES_PROFILE="${HERMES_HOME:-$HOME/.hermes/profiles/dev}"
setup_args=()

die() {
  printf 'ERRO: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
uso: install.sh [opções do bootstrap] [opções de brain setup]

Bootstrap:
  --archive-url URL   artefato .tar.gz; padrão: arquivo do MNEME_REF no GitHub
  --sha256 HASH       SHA-256 esperado do artefato
  --repository ORG/REPO
  --ref REF           branch ou tag; padrão: main
  -h, --help

As demais opções são encaminhadas ao `brain setup`, incluindo
--non-interactive, --no-mem0, --instance-root e --instance-remote.
EOF
}

need_value() {
  [[ $# -ge 2 && -n "${2:-}" ]] || die "$1 exige um valor"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive-url)
      need_value "$@"; ARCHIVE_URL="$2"; shift 2 ;;
    --sha256)
      need_value "$@"; EXPECTED_SHA256="$2"; shift 2 ;;
    --repository)
      need_value "$@"; REPOSITORY="$2"; shift 2 ;;
    --ref)
      need_value "$@"; REF="$2"; shift 2 ;;
    --non-interactive)
      INTERACTIVE=false; setup_args+=("$1"); shift ;;
    --harness)
      need_value "$@"; HARNESS="$2"; setup_args+=("$1" "$2"); shift 2 ;;
    --skills-base)
      need_value "$@"; SKILLS_BASE="$2"; setup_args+=("$1" "$2"); shift 2 ;;
    --hermes-profile)
      need_value "$@"; HERMES_PROFILE="$2"; setup_args+=("$1" "$2"); shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift; setup_args+=("$@"); break ;;
    *)
      setup_args+=("$1")
      case "$1" in
        --instance-root|--instance-remote|--drive-folder-id|--drive-remote|--rclone|--mem0-host|--mem0-user|--mem0-key-env|--package-root)
          need_value "$@"; setup_args+=("$2"); shift 2 ;;
        *) shift ;;
      esac
      ;;
  esac
done

[[ "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "repositório inválido: $REPOSITORY"
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ && "$REF" != -* && "$REF" != *..* ]] || die "ref inválida: $REF"
if [[ -n "$EXPECTED_SHA256" ]]; then
  [[ "$EXPECTED_SHA256" =~ ^[A-Fa-f0-9]{64}$ ]] || die "SHA-256 inválido"
  EXPECTED_SHA256="${EXPECTED_SHA256,,}"
fi
command -v "$PYTHON" >/dev/null 2>&1 || die "python3 não encontrado"
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Mneme requer Python 3.11 ou superior"
"$PYTHON" -c 'import venv' >/dev/null 2>&1 || die "módulo venv não disponível para $PYTHON"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum não encontrado"
command -v git >/dev/null 2>&1 || die "git não encontrado"

if [[ -z "$ARCHIVE_URL" ]]; then
  ARCHIVE_URL="https://github.com/${REPOSITORY}/archive/${REF}.tar.gz"
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/mneme-install.XXXXXXXX")"
release_stage=""
cleanup() {
  rm -rf -- "$tmp"
  [[ -z "$release_stage" ]] || rm -rf -- "$release_stage"
}
trap cleanup EXIT
archive="$tmp/mneme.tar.gz"
unpack="$tmp/unpack"
mkdir -p "$unpack"

printf 'Baixando Mneme de %s\n' "$ARCHIVE_URL"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL --proto '=https,file' --tlsv1.2 --retry 3 --output "$archive" -- "$ARCHIVE_URL"
elif command -v wget >/dev/null 2>&1; then
  wget --https-only --tries=3 --output-document="$archive" -- "$ARCHIVE_URL"
else
  die "curl ou wget é necessário"
fi

actual_sha256="$(sha256sum -- "$archive" | cut -d ' ' -f 1)"
if [[ -n "$EXPECTED_SHA256" && "$actual_sha256" != "$EXPECTED_SHA256" ]]; then
  die "checksum divergente: esperado $EXPECTED_SHA256, obtido $actual_sha256"
fi
printf 'SHA-256: %s%s\n' "$actual_sha256" "$([[ -n "$EXPECTED_SHA256" ]] && printf ' (verificado)')"

"$PYTHON" - "$archive" "$unpack" <<'PY'
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive, destination = map(Path, sys.argv[1:])
with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"ERRO: caminho inseguro no artefato: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise SystemExit(f"ERRO: tipo de entrada não permitido no artefato: {member.name}")
    bundle.extractall(destination)
PY

mapfile -t candidates < <(find "$unpack" -mindepth 1 -maxdepth 2 -type f -name VERSION -printf '%h\n')
[[ ${#candidates[@]} -eq 1 ]] || die "artefato inválido: VERSION ausente ou ambíguo"
source_root="${candidates[0]}"
[[ -f "$source_root/system/scripts/brain.py" && -f "$source_root/skills/brain-manager/SKILL.md" ]] \
  || die "artefato inválido: runtime ou skill ausente"
version="$(tr -d '[:space:]' < "$source_root/VERSION")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || die "versão inválida no artefato: $version"

mkdir -p "$INSTALL_ROOT/releases"
release="$INSTALL_ROOT/releases/$version"
if [[ -e "$release" ]]; then
  [[ -x "$release/.venv/bin/python" && -f "$release/system/scripts/brain.py" ]] \
    || die "release existente está incompleta: $release"
  printf 'Release %s já instalada; reutilizando runtime validado.\n' "$version"
else
  release_stage="$(mktemp -d "$INSTALL_ROOT/.release-${version}.XXXXXXXX")"
  cp -a "$source_root/." "$release_stage/"
  "$PYTHON" -m venv "$release_stage/.venv"
  "$release_stage/.venv/bin/python" -m pip install --disable-pip-version-check --quiet --requirement "$release_stage/requirements.lock"
  "$release_stage/.venv/bin/python" "$release_stage/system/scripts/brain.py" version >/dev/null
  mv -- "$release_stage" "$release"
  release_stage=""
fi

current_tmp="$INSTALL_ROOT/.current.$$"
ln -s "releases/$version" "$current_tmp"
mv -Tf -- "$current_tmp" "$INSTALL_ROOT/current"

mkdir -p "$BIN_DIR"
cli_stage="$(mktemp "$BIN_DIR/.brain.XXXXXXXX")"
printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail' > "$cli_stage"
printf 'INSTALL_ROOT=%q\n' "$INSTALL_ROOT" >> "$cli_stage"
cat >> "$cli_stage" <<'EOF'
PACKAGE_ROOT="${MNEME_INSTALL_ROOT:-$INSTALL_ROOT}/current"
export MNEME_PACKAGE_ROOT="$PACKAGE_ROOT"
exec "$PACKAGE_ROOT/.venv/bin/python" "$PACKAGE_ROOT/system/scripts/brain.py" --root "${MNEME_ROOT:-$HOME/mneme}" "$@"
EOF
chmod 700 "$cli_stage"
mv -f -- "$cli_stage" "$BIN_DIR/brain"

if [[ -n "$SKILLS_BASE" ]]; then
  skill_base="$SKILLS_BASE"
elif [[ "$HARNESS" == "claude" ]]; then
  skill_base="${CLAUDE_HOME:-$HOME/.claude}"
else
  skill_base="$HERMES_PROFILE"
fi
skill_parent="$skill_base/skills"
skill_target="$skill_parent/brain-manager"
mkdir -p "$skill_parent"
skill_stage="$(mktemp -d "$skill_parent/.brain-manager.XXXXXXXX")"
cp -a "$release/skills/brain-manager/." "$skill_stage/"
chmod +x "$skill_stage"/scripts/* 2>/dev/null || true
skill_backup=""
if [[ -e "$skill_target" ]]; then
  skill_backup="$skill_parent/.brain-manager.backup.$$"
  mv -- "$skill_target" "$skill_backup"
fi
if ! mv -- "$skill_stage" "$skill_target"; then
  [[ -n "$skill_backup" ]] && mv -- "$skill_backup" "$skill_target"
  die "não foi possível promover a skill"
fi
[[ -n "$skill_backup" ]] && rm -rf -- "$skill_backup"

setup_command=("$release/.venv/bin/python" "$release/system/scripts/brain.py" setup --no-install "${setup_args[@]}")
if $INTERACTIVE && { exec 3<>/dev/tty; } 2>/dev/null; then
  "${setup_command[@]}" <&3 >&3
  exec 3>&- 3<&-
else
  "${setup_command[@]}"
fi

printf '\nMneme %s instalado.\n' "$version"
printf 'runtime  : %s\n' "$release"
printf 'current  : %s/current\n' "$INSTALL_ROOT"
printf 'CLI      : %s/brain\n' "$BIN_DIR"
printf 'skill    : %s\n' "$skill_target"
printf 'instância: %s\n' "${MNEME_ROOT:-$HOME/mneme}"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  printf 'aviso    : adicione %s ao PATH\n' "$BIN_DIR"
fi
