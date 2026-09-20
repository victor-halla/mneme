#!/usr/bin/env bash
# Bootstrap público do Mneme. Baixa e instala o pacote sem alterar o Python do sistema.
#
# Ordem de execução:
#   1. preflight de dependências e argumentos;
#   2. download, checksum e extração com limites;
#   3. release versionada em staging (venv + manifesto);
#   4. staging de CLI e skill;
#   5. validação do plano de configuração (`brain setup --check`);
#   6. promoção de current, CLI e skill, com rollback em caso de falha;
#   7. criação ou adoção da instância.
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
INSTANCE_ROOT="${MNEME_ROOT:-$HOME/mneme}"
setup_args=()

MAX_ARCHIVE_BYTES=134217728   # 128 MiB
MAX_UNPACKED_BYTES=536870912  # 512 MiB
MAX_MEMBERS=20000

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
      need_value "$@"
      [[ "$2" == "hermes" || "$2" == "claude" ]] || die "harness inválido: $2 (use hermes ou claude)"
      HARNESS="$2"; setup_args+=("$1" "$2"); shift 2 ;;
    --skills-base)
      need_value "$@"; SKILLS_BASE="$2"; setup_args+=("$1" "$2"); shift 2 ;;
    --hermes-profile)
      need_value "$@"; HERMES_PROFILE="$2"; setup_args+=("$1" "$2"); shift 2 ;;
    --instance-root|--root)
      need_value "$@"; INSTANCE_ROOT="$2"; setup_args+=("$1" "$2"); shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift; setup_args+=("$@"); break ;;
    *)
      setup_args+=("$1")
      case "$1" in
        --instance-remote|--drive-folder-id|--drive-remote|--rclone|--mem0-host|--mem0-user|--mem0-key-env|--package-root)
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

# -- estado temporário e rollback ----------------------------------------------

tmp="$(mktemp -d "${TMPDIR:-/tmp}/mneme-install.XXXXXXXX")"
release_stage=""
current_backup=""
current_created=false
cli_backup=""
skill_backup=""
promoted=false

cleanup() {
  rm -rf -- "$tmp"
  [[ -z "$release_stage" ]] || rm -rf -- "$release_stage"
}
rollback() {
  local status=$?
  if [[ "$promoted" == false ]]; then
    if [[ "$current_created" == true ]]; then
      rm -f -- "$INSTALL_ROOT/current"
    else
      [[ -z "$current_backup" ]] || ln -sfn -- "$current_backup" "$INSTALL_ROOT/current"
    fi
    [[ -z "$cli_backup" ]] || mv -f -- "$cli_backup" "$BIN_DIR/brain"
    if [[ -n "$skill_backup" ]]; then
      rm -rf -- "${skill_target:-}"
      mv -- "$skill_backup" "${skill_target:-}"
    fi
    printf 'ERRO: instalação revertida; os artefatos anteriores foram restaurados.\n' >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap rollback ERR

mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
# Instaladores concorrentes não podem disputar a mesma release e os mesmos alvos.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$INSTALL_ROOT/.install.lock"
  flock -w 300 9 || die "outra instalação do Mneme está em andamento"
fi

# -- download, checksum e extração ---------------------------------------------

archive="$tmp/mneme.tar.gz"
case "$ARCHIVE_URL" in
  file://*)
    source_path="${ARCHIVE_URL#file://}"
    [[ -f "$source_path" ]] || die "arquivo local não encontrado: $source_path"
    cp -- "$source_path" "$archive" ;;
  https://*)
    printf 'Baixando Mneme de %s\n' "$ARCHIVE_URL"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL --proto '=https' --tlsv1.2 --retry 3 \
        --max-filesize "$MAX_ARCHIVE_BYTES" --output "$archive" -- "$ARCHIVE_URL"
    elif command -v wget >/dev/null 2>&1; then
      wget --https-only --tries=3 --max-redirect=3 --output-document="$archive" -- "$ARCHIVE_URL"
    else
      die "curl ou wget é necessário para baixar por HTTPS"
    fi ;;
  *)
    die "URL não suportada: use https:// ou file://" ;;
esac
[[ -f "$archive" ]] || die "download não produziu arquivo"
archive_size="$(wc -c < "$archive")"
(( archive_size > 0 )) || die "artefato vazio"
(( archive_size <= MAX_ARCHIVE_BYTES )) || die "artefato maior que o limite permitido"

actual_sha256="$(sha256sum -- "$archive" | cut -d ' ' -f 1)"
if [[ -n "$EXPECTED_SHA256" && "$actual_sha256" != "$EXPECTED_SHA256" ]]; then
  die "checksum divergente: esperado $EXPECTED_SHA256, obtido $actual_sha256"
fi
printf 'SHA-256: %s%s\n' "$actual_sha256" "$([[ -n "$EXPECTED_SHA256" ]] && printf ' (verificado)')"

unpack="$tmp/unpack"
mkdir -p "$unpack"
"$PYTHON" - "$archive" "$unpack" "$MAX_MEMBERS" "$MAX_UNPACKED_BYTES" <<'PY'
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive, destination = Path(sys.argv[1]), Path(sys.argv[2])
max_members, max_unpacked = int(sys.argv[3]), int(sys.argv[4])

with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    if len(members) > max_members:
        raise SystemExit(f"ERRO: artefato com entradas demais ({len(members)})")
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"ERRO: caminho inseguro no artefato: {member.name}")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise SystemExit(f"ERRO: tipo de entrada não permitido no artefato: {member.name}")
        total += member.size
        if total > max_unpacked:
            raise SystemExit("ERRO: artefato descompactado maior que o limite permitido")
    bundle.extractall(destination)
PY

mapfile -t candidates < <(find "$unpack" -mindepth 1 -maxdepth 2 -type f -name VERSION -printf '%h\n')
[[ ${#candidates[@]} -eq 1 ]] || die "artefato inválido: VERSION ausente ou ambíguo"
source_root="${candidates[0]}"
[[ -f "$source_root/system/scripts/brain.py" && -f "$source_root/skills/brain-manager/SKILL.md" ]] \
  || die "artefato inválido: runtime ou skill ausente"
version="$(tr -d '[:space:]' < "$source_root/VERSION")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || die "versão inválida no artefato: $version"

# -- release versionada --------------------------------------------------------

mkdir -p "$INSTALL_ROOT/releases"
release="$INSTALL_ROOT/releases/$version"
manifest() { printf '%s\n' "$1/.mneme-release.json"; }

if [[ -e "$release" ]]; then
  [[ -f "$(manifest "$release")" ]] || die "release $version existe sem manifesto; remova-a ou publique outra versão"
  recorded="$(grep -o '"archive_sha256": *"[a-f0-9]*"' "$(manifest "$release")" | cut -d '"' -f 4)"
  [[ "$recorded" == "$actual_sha256" ]] \
    || die "versão $version já instalada com conteúdo diferente (hash $recorded); versões publicadas são imutáveis"
  printf 'Release %s já instalada com o mesmo conteúdo; reutilizando.\n' "$version"
else
  release_stage="$(mktemp -d "$INSTALL_ROOT/.release-${version}.XXXXXXXX")"
  cp -a "$source_root/." "$release_stage/"
  "$PYTHON" -m venv "$release_stage/.venv"
  "$release_stage/.venv/bin/python" -m pip install --disable-pip-version-check --quiet \
    --no-deps --require-hashes --requirement "$release_stage/requirements.lock"
  "$release_stage/.venv/bin/python" "$release_stage/system/scripts/brain.py" version >/dev/null
  printf '{\n  "version": "%s",\n  "archive_sha256": "%s",\n  "source": "%s"\n}\n' \
    "$version" "$actual_sha256" "$ARCHIVE_URL" > "$(manifest "$release_stage")"
  mv -- "$release_stage" "$release"
  release_stage=""
fi

# -- staging de CLI e skill ----------------------------------------------------

cli_stage="$(mktemp "$BIN_DIR/.brain.XXXXXXXX")"
{
  printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail'
  printf 'INSTALL_ROOT=%q\n' "$INSTALL_ROOT"
  printf 'DEFAULT_ROOT=%q\n' "$INSTANCE_ROOT"
  cat <<'EOF'
PACKAGE_ROOT="${MNEME_INSTALL_ROOT:-$INSTALL_ROOT}/current"
export MNEME_PACKAGE_ROOT="$PACKAGE_ROOT"
exec "$PACKAGE_ROOT/.venv/bin/python" "$PACKAGE_ROOT/system/scripts/brain.py" --root "${MNEME_ROOT:-$DEFAULT_ROOT}" "$@"
EOF
} > "$cli_stage"
chmod 700 "$cli_stage"

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
printf '%s\n' "$INSTALL_ROOT/current" > "$skill_stage/scripts/.package-root"
chmod +x "$skill_stage"/scripts/* 2>/dev/null || true

# -- validação do plano antes de qualquer promoção -----------------------------

"$release/.venv/bin/python" "$release/system/scripts/brain.py" setup --check --no-install \
  --package-root "$INSTALL_ROOT/current" "${setup_args[@]}" >/dev/null \
  || die "opções de configuração inválidas; nada foi promovido"

# -- promoção com rollback -----------------------------------------------------

if [[ -L "$INSTALL_ROOT/current" ]]; then
  current_backup="$(readlink "$INSTALL_ROOT/current")"
else
  current_created=true
fi
ln -sfn "releases/$version" "$INSTALL_ROOT/current"

if [[ -e "$BIN_DIR/brain" ]]; then
  cli_backup="$(mktemp "$BIN_DIR/.brain-old.XXXXXXXX")"
  cp -p -- "$BIN_DIR/brain" "$cli_backup"
fi
mv -f -- "$cli_stage" "$BIN_DIR/brain"

if [[ -e "$skill_target" ]]; then
  skill_backup="$skill_parent/.brain-manager.backup.$$"
  mv -- "$skill_target" "$skill_backup"
fi
mv -- "$skill_stage" "$skill_target"
promoted=true
[[ -z "$skill_backup" ]] || { rm -rf -- "$skill_backup"; skill_backup=""; }
[[ -z "$cli_backup" ]] || { rm -f -- "$cli_backup"; cli_backup=""; }
trap - ERR

# -- configuração da instância -------------------------------------------------

setup_command=(
  "$release/.venv/bin/python"
  "$release/system/scripts/brain.py"
  setup
  --no-install
  --package-root "$INSTALL_ROOT/current"
  "${setup_args[@]}"
)
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
printf 'instância: %s\n' "$INSTANCE_ROOT"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  printf 'aviso    : adicione %s ao PATH\n' "$BIN_DIR"
fi
