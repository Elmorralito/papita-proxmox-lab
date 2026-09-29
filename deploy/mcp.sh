#!/usr/bin/env bash
# Install, update, test, and sync Cursor MCP servers under mcp/.
# shellcheck disable=SC1090,SC1091
set -euo pipefail

ACTION=
MCP_SERVER=
SMOKE_EXTENDED=0
SYNC_IF_CHANGED=0
SYNC_ENABLE_AGENT=0
# Scope for Cursor mcp.json targets: user | project | both | "" (unset)
# install/update default to both; cursor-sync defaults to user unless --all-targets/--scope set.
MCP_SCOPE=
SYNC_MCP_CONFIG=1
SYNC_ALL_TARGETS=0
CURSOR_MCP_JSON="${CURSOR_MCP_JSON:-${HOME}/.cursor/mcp.json}"
CURSOR_MCP_PROJECT_JSON=

PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
MCP_ROOT="${PROJECT_PATH}/mcp"
MCP_SYNC_FINGERPRINT="${PROJECT_PATH}/.cursor/.mcp-sync-fingerprint"
CURSOR_MCP_PROJECT_JSON="${PROJECT_PATH}/.cursor/mcp.json"
CURSOR_MCP_USER_JSON="${HOME}/.cursor/mcp.json"
SKILLS_SRC="${PROJECT_PATH}/.cursor/skills"
SKILLS_USER_DST="${HOME}/.cursor/skills"
SYNC_SKILLS=1

# shellcheck source=${PROJECT_PATH}/deploy/utils.sh
{
    cd "${PROJECT_PATH}" && source "${PROJECT_PATH}/deploy/utils.sh"
} || {
    echo "[ERROR] Runtime - cannot load utils path."
    exit 255
}

# shellcheck source=${PROJECT_PATH}/deploy/usage.sh
source "${PROJECT_PATH}/deploy/usage.sh"

if ! command -v poetry >/dev/null 2>&1; then
    log "ERROR" "poetry is not installed."
    exit 255
fi

if ! command -v jq >/dev/null 2>&1; then
    log "ERROR" "jq is not installed."
    exit 255
fi

_mcp_packages() {
    local dir
    for dir in "${MCP_ROOT}"/*; do
        [[ -d "${dir}" ]] || continue
        [[ -f "${dir}/pyproject.toml" ]] || continue
        basename "${dir}"
    done
}

_mcp_package_path() {
    local name="$1"
    echo "${MCP_ROOT}/${name}"
}

_resolve_server_package() {
    local server="${1:-}"
    if [[ -n "${server}" ]]; then
        local pkg="${server}"
        [[ "${pkg}" != *-mcp ]] && pkg="${server}-mcp"
        if [[ ! -f "${MCP_ROOT}/${pkg}/pyproject.toml" ]]; then
            log "ERROR" "Unknown MCP server '${server}' (no package ${MCP_ROOT}/${pkg})."
            exit 1
        fi
        echo "${pkg}"
        return
    fi
    _mcp_packages
}

_poetry_install_root() {
    log "INFO" "Installing repo Poetry environment (includes path deps)..."
    cd "${PROJECT_PATH}"
    poetry lock
    poetry install --with test --no-interaction
}

_install_package_scripts() {
    local pkg="$1"
    local pkg_path
    pkg_path="$(_mcp_package_path "${pkg}")"
    log "INFO" "Registering console scripts for ${pkg}..."
    poetry run pip install -e "${pkg_path}" --no-deps --force-reinstall --no-cache-dir
}

cmd_list() {
    log "INFO" "MCP packages under ${MCP_ROOT}:"
    local pkg
    for pkg in $(_mcp_packages); do
        local version scripts
        version="$(grep -E '^version = ' "${MCP_ROOT}/${pkg}/pyproject.toml" | head -1 | sed 's/version = "\(.*\)"/\1/')"
        scripts="$(python3 -c "
import tomllib, pathlib
data = tomllib.loads(pathlib.Path('${MCP_ROOT}/${pkg}/pyproject.toml').read_text())
print(' '.join(data.get('project', {}).get('scripts', {}).keys()))
" 2>/dev/null || echo none)"
        printf '  - %s (v%s) scripts: %s\n' "${pkg}" "${version:-?}" "${scripts:-none}"
        if [[ -f "${MCP_ROOT}/${pkg}/mcp.json.example" ]]; then
            jq -r '.mcpServers | keys[]' "${MCP_ROOT}/${pkg}/mcp.json.example" 2>/dev/null \
                | sed "s/^/      cursor server: /" || true
        fi
    done
    log "INFO" "Bundled Cursor skills under ${SKILLS_SRC}:"
    local skill
    for skill in $(_mcp_bundled_skills); do
        if [[ -f "${SKILLS_SRC}/${skill}/SKILL.md" ]]; then
            printf '  - %s (project)\n' "${skill}"
            if [[ -L "${SKILLS_USER_DST}/${skill}" || -d "${SKILLS_USER_DST}/${skill}" ]]; then
                printf '      user: %s\n' "${SKILLS_USER_DST}/${skill}"
            fi
        else
            printf '  - %s (MISSING)\n' "${skill}"
        fi
    done
}

# Skills that teach agents when/how to invoke MCP servers (and the repo map).
_mcp_bundled_skills() {
    printf '%s\n' \
        papita-proxmox-lab-map \
        proxmox-ve-mcp \
        truenas-mcp
}

_verify_project_skills() {
    local skill missing=0
    for skill in $(_mcp_bundled_skills); do
        if [[ ! -f "${SKILLS_SRC}/${skill}/SKILL.md" ]]; then
            log "ERROR" "Missing project skill: ${SKILLS_SRC}/${skill}/SKILL.md"
            missing=1
        fi
    done
    if [[ "${missing}" -ne 0 ]]; then
        exit 1
    fi
    log "INFO" "Project skills present under ${SKILLS_SRC}."
}

_rewrite_skill_repo_links() {
    # User copies live outside the repo; rewrite ../../../… → absolute PROJECT_PATH.
    local dest_dir="$1"
    local f
    while IFS= read -r -d '' f; do
        sed -i "s|](\.\./\.\./\.\./|](${PROJECT_PATH}/|g" "${f}"
    done < <(find "${dest_dir}" -type f -name '*.md' -print0 2>/dev/null)
}

_install_skill_to_user() {
    local skill="$1"
    local src="${SKILLS_SRC}/${skill}"
    local dst="${SKILLS_USER_DST}/${skill}"
    mkdir -p "${SKILLS_USER_DST}"
    rm -rf "${dst}"
    mkdir -p "${dst}"
    cp -a "${src}/." "${dst}/"
    _rewrite_skill_repo_links "${dst}"
    log "INFO" "Installed skill '${skill}' → ${dst}"
}

_install_skills_for_scope() {
    if [[ "${SYNC_SKILLS}" -eq 0 ]]; then
        log "INFO" "Skipping Cursor skills install (--no-skills)."
        return 0
    fi
    _verify_project_skills
    local scope="${MCP_SCOPE:-both}"
    case "${scope}" in
    project)
        log "INFO" "Skills scope=project: using ${SKILLS_SRC} (no user copy)."
        ;;
    user | both)
        local skill
        for skill in $(_mcp_bundled_skills); do
            _install_skill_to_user "${skill}"
        done
        if [[ "${scope}" == "both" ]]; then
            log "INFO" "Skills scope=both: project source + user copies under ${SKILLS_USER_DST}."
        fi
        ;;
    esac
}

cmd_skills_sync() {
    _validate_mcp_scope
    if [[ -z "${MCP_SCOPE}" ]]; then
        MCP_SCOPE="both"
    fi
    _install_skills_for_scope
}

_validate_mcp_scope() {
    case "${MCP_SCOPE}" in
    "" | user | project | both) ;;
    *)
        log "ERROR" "Invalid --scope '${MCP_SCOPE}' (expected: user, project, or both)."
        usage_mcp
        ;;
    esac
}

_resolve_sync_targets() {
    # Prints one mcp.json path per line for the active scope.
    # Prefer MCP_SCOPE; fall back to legacy --all-targets / single CURSOR_MCP_JSON.
    local scope="${MCP_SCOPE}"
    if [[ -z "${scope}" ]]; then
        if [[ "${SYNC_ALL_TARGETS:-0}" -eq 1 ]]; then
            scope="both"
        else
            # Single explicit -c path, or default user config
            echo "${CURSOR_MCP_JSON}"
            return
        fi
    fi
    case "${scope}" in
    user)
        echo "${CURSOR_MCP_USER_JSON}"
        ;;
    project)
        echo "${CURSOR_MCP_PROJECT_JSON}"
        ;;
    both)
        echo "${CURSOR_MCP_USER_JSON}"
        echo "${CURSOR_MCP_PROJECT_JSON}"
        ;;
    esac
}

_sync_for_scope() {
    if [[ "${SYNC_MCP_CONFIG}" -eq 0 ]]; then
        log "INFO" "Skipping Cursor mcp.json sync (--no-sync)."
        return 0
    fi
    local scope_label="${MCP_SCOPE:-user}"
    [[ "${SYNC_ALL_TARGETS:-0}" -eq 1 && -z "${MCP_SCOPE}" ]] && scope_label="both"
    log "INFO" "Syncing Cursor MCP config (scope=${scope_label})..."
    cmd_cursor_sync
}

cmd_install() {
    _validate_mcp_scope
    # Default install/update scope: both (user + project Cursor configs)
    if [[ -z "${MCP_SCOPE}" ]]; then
        MCP_SCOPE="both"
    fi
    _poetry_install_root
    local pkg
    for pkg in $(_resolve_server_package "${MCP_SERVER}"); do
        _install_package_scripts "${pkg}"
    done
    _sync_for_scope
    _install_skills_for_scope
    log "INFO" "MCP install complete (scope=${MCP_SCOPE}). Next: edit secrets if needed, then ./deploy/mcp.sh smoke --extended"
}

cmd_update() {
    _validate_mcp_scope
    if [[ -z "${MCP_SCOPE}" ]]; then
        MCP_SCOPE="both"
    fi
    log "INFO" "Updating MCP packages (re-lock, reinstall, refresh scripts, sync scope=${MCP_SCOPE})..."
    _poetry_install_root
    local pkg
    for pkg in $(_resolve_server_package "${MCP_SERVER}"); do
        _install_package_scripts "${pkg}"
    done
    _sync_for_scope
    _install_skills_for_scope
    log "INFO" "MCP update complete (scope=${MCP_SCOPE}). Reload Cursor if entry points changed."
}

cmd_test() {
    _poetry_install_root
    log "INFO" "Running MCP unit tests..."
    cd "${PROJECT_PATH}"
    local paths=()
    local pkg
    for pkg in $(_resolve_server_package "${MCP_SERVER}"); do
        paths+=("mcp/${pkg}/tests")
    done
    poetry run pytest "${paths[@]}" -q
    log "INFO" "MCP tests passed."
}

cmd_smoke() {
    _poetry_install_root
    local pkg="${MCP_SERVER:-proxmox-ve-mcp}"
    pkg="$(_resolve_server_package "${pkg}")"

    case "${pkg}" in
    proxmox-ve-mcp)
        if [[ ! -x "${PROJECT_PATH}/.venv/bin/proxmox-ve-mcp-smoke" ]]; then
            _install_package_scripts "${pkg}"
        fi
        ;;
    pfsense-mcp)
        if [[ ! -x "${PROJECT_PATH}/.venv/bin/pfsense-mcp-smoke" ]]; then
            _install_package_scripts "${pkg}"
        fi
        if [[ ! -x "${PROJECT_PATH}/.venv/bin/pfsense-mcp-bootstrap" ]]; then
            _install_package_scripts "${pkg}"
        fi
        ;;
    truenas-mcp)
        if [[ ! -x "${PROJECT_PATH}/.venv/bin/truenas-mcp-smoke" ]]; then
            _install_package_scripts "${pkg}"
        fi
        ;;
    *)
        log "ERROR" "No smoke CLI for ${pkg}. See mcp/${pkg}/README.md."
        exit 1
        ;;
    esac

    local smoke_args=()
    local cursor_server=""
    case "${pkg}" in
    proxmox-ve-mcp)
        smoke_args=(poetry run proxmox-ve-mcp-smoke)
        cursor_server="proxmox-ve"
        [[ "${SMOKE_EXTENDED}" -eq 1 ]] && smoke_args+=(--extended)
        ;;
    pfsense-mcp)
        smoke_args=(poetry run pfsense-mcp-smoke)
        cursor_server="pfsense"
        ;;
    truenas-mcp)
        smoke_args=(poetry run truenas-mcp-smoke)
        cursor_server="truenas"
        [[ "${SMOKE_EXTENDED}" -eq 1 ]] && smoke_args+=(--extended)
        ;;
    esac

    if [[ -f "${CURSOR_MCP_JSON}" ]] && jq -e ".mcpServers[\"${cursor_server}\"].env" "${CURSOR_MCP_JSON}" >/dev/null 2>&1; then
        log "INFO" "Loading credentials from ${CURSOR_MCP_JSON} for smoke test (${cursor_server})."
        # shellcheck disable=SC1090
        eval "$(jq -r ".mcpServers[\"${cursor_server}\"].env | to_entries[] | \"export \(.key)=\(.value|@sh)\"" "${CURSOR_MCP_JSON}")"
    else
        log "WARN" "No ${cursor_server} env in ${CURSOR_MCP_JSON}; ensure variables are set."
    fi

    if [[ "${pkg}" == "pfsense-mcp" && -f "${PROJECT_PATH}/.env" ]]; then
        log "INFO" "Loading Tailscale Admin API vars from ${PROJECT_PATH}/.env (if present)."
        # shellcheck disable=SC1090
        set -a
        # shellcheck source=/dev/null
        source "${PROJECT_PATH}/.env"
        set +a
    fi

    cd "${PROJECT_PATH}"
    log "INFO" "Running smoke test (${pkg})..."
    "${smoke_args[@]}"
}

_merge_example_into_config() {
    local example_file="$1"
    local tmp merged
    tmp="$(mktemp)"
    merged="$(mktemp)"
    sed "s|/absolute/path/to/papita-proxmox-lab|${PROJECT_PATH}|g" "${example_file}" > "${tmp}"

    if [[ ! -f "${CURSOR_MCP_JSON}" ]]; then
        mkdir -p "$(dirname "${CURSOR_MCP_JSON}")"
        cp "${tmp}" "${CURSOR_MCP_JSON}"
        log "INFO" "Created ${CURSOR_MCP_JSON} from $(basename "${example_file}")."
        rm -f "${tmp}" "${merged}"
        return
    fi

    jq -s '
        .[0] as $base |
        .[1] as $add |
        reduce ($add.mcpServers | keys[]) as $k ($base;
            if .mcpServers[$k] then
                .mcpServers[$k].command = $add.mcpServers[$k].command |
                .mcpServers[$k].args = $add.mcpServers[$k].args |
                .mcpServers[$k].cwd = $add.mcpServers[$k].cwd |
                .mcpServers[$k].env = (($add.mcpServers[$k].env // {}) * (.mcpServers[$k].env // {}))
            else
                .mcpServers[$k] = $add.mcpServers[$k]
            end
        )
    ' "${CURSOR_MCP_JSON}" "${tmp}" > "${merged}"
    mv "${merged}" "${CURSOR_MCP_JSON}"
    rm -f "${tmp}"
    log "INFO" "Merged $(basename "${example_file}") into ${CURSOR_MCP_JSON} (existing env values preserved; new keys added)."
}

_mcp_examples_fingerprint() {
    local examples=()
    local pkg
    for pkg in $(_mcp_packages); do
        [[ -f "${MCP_ROOT}/${pkg}/mcp.json.example" ]] && examples+=("${MCP_ROOT}/${pkg}/mcp.json.example")
    done
    if [[ "${#examples[@]}" -eq 0 ]]; then
        echo "none"
        return
    fi
    shasum -a 256 "${examples[@]}" | shasum -a 256 | awk '{print $1}'
}

_mcp_sync_needed() {
    [[ "${SYNC_IF_CHANGED}" -eq 0 ]] && return 0
    local current stored
    current="$(_mcp_examples_fingerprint)"
    if [[ ! -f "${MCP_SYNC_FINGERPRINT}" ]]; then
        return 0
    fi
    stored="$(tr -d '[:space:]' < "${MCP_SYNC_FINGERPRINT}")"
    [[ "${current}" != "${stored}" ]]
}

_mcp_write_sync_fingerprint() {
    mkdir -p "$(dirname "${MCP_SYNC_FINGERPRINT}")"
    _mcp_examples_fingerprint > "${MCP_SYNC_FINGERPRINT}"
}

_cursor_sync_targets() {
    local found=0
    local pkg example
    for pkg in $(_mcp_packages); do
        example="${MCP_ROOT}/${pkg}/mcp.json.example"
        if [[ -f "${example}" ]]; then
            found=1
            _merge_example_into_config "${example}"
        fi
    done
    if [[ "${found}" -eq 0 ]]; then
        log "WARN" "No mcp.json.example files found under ${MCP_ROOT}."
        exit 1
    fi
}

_enable_cursor_agent_mcps() {
    if [[ "${SYNC_ENABLE_AGENT}" -eq 0 ]]; then
        return 0
    fi
    if ! command -v cursor-agent >/dev/null 2>&1; then
        log "WARN" "cursor-agent not on PATH; skipping MCP enable."
        return 0
    fi
    local pkg example server
    for pkg in $(_mcp_packages); do
        example="${MCP_ROOT}/${pkg}/mcp.json.example"
        [[ -f "${example}" ]] || continue
        while IFS= read -r server; do
            [[ -n "${server}" ]] || continue
            if cursor-agent mcp enable "${server}" >/dev/null 2>&1; then
                log "INFO" "cursor-agent: enabled MCP server '${server}'."
            fi
        done < <(jq -r '.mcpServers | keys[]' "${example}" 2>/dev/null)
    done
}

cmd_cursor_sync() {
    _validate_mcp_scope
    if ! _mcp_sync_needed; then
        log "INFO" "MCP examples unchanged; skipping cursor-sync (--if-changed)."
        return 0
    fi

    local -a targets=()
    local target
    while IFS= read -r target; do
        [[ -n "${target}" ]] && targets+=("${target}")
    done < <(_resolve_sync_targets)

    if [[ "${#targets[@]}" -eq 0 ]]; then
        log "ERROR" "No Cursor mcp.json sync targets resolved."
        exit 1
    fi

    for target in "${targets[@]}"; do
        if [[ "${target}" == "${CURSOR_MCP_PROJECT_JSON}" \
            && ! -f "${target}" \
            && -f "${CURSOR_MCP_USER_JSON}" ]]; then
            mkdir -p "$(dirname "${target}")"
            cp "${CURSOR_MCP_USER_JSON}" "${target}"
            log "INFO" "Seeded ${target} from ${CURSOR_MCP_USER_JSON} (env secrets copied)."
        fi
        CURSOR_MCP_JSON="${target}"
        _cursor_sync_targets
    done

    _mcp_write_sync_fingerprint
    _enable_cursor_agent_mcps
    log "INFO" "Cursor MCP config synced. Reload Cursor or restart cursor-agent if servers changed."
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
    list | install | update | test | smoke | cursor-sync | skills-sync)
        ACTION="$1"
        shift
        ;;
    --server | -s)
        MCP_SERVER="$2"
        shift 2
        ;;
    --extended)
        SMOKE_EXTENDED=1
        shift
        ;;
    --scope)
        MCP_SCOPE="$2"
        shift 2
        ;;
    --no-sync)
        SYNC_MCP_CONFIG=0
        shift
        ;;
    --no-skills)
        SYNC_SKILLS=0
        shift
        ;;
    --cursor-config | -c)
        CURSOR_MCP_JSON="$2"
        shift 2
        ;;
    --all-targets)
        # Legacy alias for --scope both
        SYNC_ALL_TARGETS=1
        MCP_SCOPE="both"
        shift
        ;;
    --if-changed)
        SYNC_IF_CHANGED=1
        shift
        ;;
    --enable-agent)
        SYNC_ENABLE_AGENT=1
        shift
        ;;
    --help | -h)
        usage_mcp
        ;;
    *)
        log "ERROR" "Unknown argument: $1"
        usage_mcp
        ;;
    esac
done

if [[ -z "${ACTION}" ]]; then
    log "ERROR" "Action is required."
    usage_mcp
fi

case "${ACTION}" in
list)
    cmd_list
    ;;
install)
    cmd_install
    ;;
update)
    cmd_update
    ;;
test)
    cmd_test
    ;;
smoke)
    cmd_smoke
    ;;
cursor-sync)
    cmd_cursor_sync
    ;;
skills-sync)
    cmd_skills_sync
    ;;
esac

log "INFO" "Done."
