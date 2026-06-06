#!/bin/bash

GREEN_TEXT='\033[0;32m'
RED_TEXT='\033[0;31m'
YELLOW_TEXT='\033[0;33m'
BLUE_TEXT='\033[0;34m'
NC_TEXT='\033[0m'
# No tput: works when TERM is unset (SSH, IDE terminals). SGR bold on/off; does not reset colors.
BOLD_TEXT='\033[1m'
NORMAL_TEXT='\033[22m'

log() {
    local level="$1"
    shift
    local color="${NC_TEXT}"
    if [[ "${level}" == "ERROR" ]]; then
        color="${RED_TEXT}"
    elif [[ "${level}" == "INFO" ]]; then
        color="${GREEN_TEXT}"
    elif [[ "${level}" == "WARN" ]]; then
        color="${YELLOW_TEXT}"
    elif [[ "${level}" == "QUESTION" ]]; then
        color="${BLUE_TEXT}"
    elif [[ "$level" == "TRACE" ]]; then
        color="${NC_TEXT}"
        echo -e "$*"
        return
    fi
    echo -e "${color}$(date +"%Y-%m-%d %H:%M:%S") :: ${BOLD_TEXT}$(basename "$0")${NORMAL_TEXT} ${color}:: ${BOLD_TEXT}${level}${NORMAL_TEXT} ${color}:: $*${NC_TEXT}"
}

# -----------------------------------------------------------------------------
# Interactive prompts (shared by setup-pve-node.sh: repo checkout or remote deploy)
# Requires: log(). Uses bash namerefs (bash 4.3+).
# -----------------------------------------------------------------------------

# Trim leading/trailing whitespace (bash parameter expansion).
_str_trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

# Print non-empty, non-comment lines from a list file (# to EOL is a comment).
# Fails when the file is missing or unreadable.
list_file_active_lines() {
    local list_file="$1"
    if [[ ! -f "$list_file" ]]; then
        return 1
    fi
    sed '/^[[:space:]]*$/d;/^[[:space:]]*#/d' "$list_file"
}

# Comma-separated active lines (e.g. Tailscale --advertise-routes / --advertise-tags).
list_file_csv() {
    list_file_active_lines "$1" | paste -sd, -
}

# First active line (e.g. a single regex or default value in a .list file).
list_file_first_line() {
    list_file_active_lines "$1" | head -n1
}

# Print prompt in QUESTION color (blue), then read one line into nameref.
_prompt_read_line() {
    local prompt_text="$1"
    local -n _out_var="$2"
    printf '%b%s%b' "${BLUE_TEXT}" "${prompt_text}" "${NC_TEXT}" >&2
    read -r _out_var || return 1
}

# Loop until user enters y or n (case-insensitive). Second arg: name of variable to set.
prompt_until_yn() {
    local prompt_text="$1"
    local -n _out_yn="$2"
    local line lowered
    while true; do
        _prompt_read_line "$prompt_text" line || return 1
        line="$(_str_trim "$line")"
        lowered="${line,,}"
        case "$lowered" in
            y | n)
                _out_yn="$lowered"
                return 0
                ;;
            *)
                log WARN "Please enter y or n."
                ;;
        esac
    done
}

# Loop until y or n (case-insensitive). e/t log and exit the whole script with status 0.
prompt_until_ynet() {
    local prompt_text="$1"
    local -n _out_ynet="$2"
    local line lowered
    while true; do
        _prompt_read_line "$prompt_text" line || return 1
        line="$(_str_trim "$line")"
        lowered="${line,,}"
        case "$lowered" in
            y | n)
                _out_ynet="$lowered"
                return 0
                ;;
            e | t)
                log INFO "Exiting setup."
                exit 0
                ;;
            *)
                log WARN "Please enter y (yes), n (no), or e/t (exit setup)."
                ;;
        esac
    done
}

# Loop until y, c, or n (Tailscale install vs continue-only).
prompt_until_ycnet() {
    local prompt_text="$1"
    local -n _out_ycnet="$2"
    local line lowered
    while true; do
        _prompt_read_line "$prompt_text" line || return 1
        line="$(_str_trim "$line")"
        lowered="${line,,}"
        case "$lowered" in
            y | c | n)
                _out_ycnet="$lowered"
                return 0
                ;;
            e | t)
                log INFO "Exiting setup."
                exit 0
                ;;
            *)
                log WARN "Please enter y (install), c (continue without install), or n (skip)."
                ;;
        esac
    done
}

# Loop until y, ?, or n (help vs proceed vs skip).
prompt_until_yqnet() {
    local prompt_text="$1"
    local -n _out_yqnet="$2"
    local line lowered
    while true; do
        _prompt_read_line "$prompt_text" line || return 1
        line="$(_str_trim "$line")"
        lowered="${line,,}"
        case "$lowered" in
            y)
                _out_yqnet="y"
                return 0
                ;;
            n)
                _out_yqnet="n"
                return 0
                ;;
            '?')
                _out_yqnet="?"
                return 0
                ;;
            e | t)
                log INFO "Exiting setup."
                exit 0
                ;;
            *)
                log WARN "Please enter y (yes), ? (help), n (no), or e/t (exit setup)."
                ;;
        esac
    done
}

# Initial PVE menu: empty, y, n, or step 1–N (N = PVE_SETUP_LAST_STEP in setup-pve-node.sh).
prompt_pve_start() {
    local -n _out_start="$1"
    local line lowered max_step
    max_step="$2"
    while true; do
        _prompt_read_line "Input: " line || return 1
        line="$(_str_trim "$line")"
        if [ -z "$line" ]; then
            _out_start=""
            return 0
        fi
        lowered="${line,,}"
        case "$lowered" in
            y | n)
                _out_start="$lowered"
                return 0
                ;;
            h | help | '?' | usage | -h | --help)
                _out_start="__USAGE__"
                return 0
                ;;
        esac
        if [[ "$line" =~ ^[0-9]+$ ]] && ((line >= 1 && line <= max_step)); then
            _out_start="$line"
            return 0
        fi
        log WARN "Enter y, n, h/help/?/usage/-h/--help for usage, a step number (1-${max_step}), or leave empty to start from the beginning."
    done
}

# Crontab line: empty -> default; otherwise five time fields (step/user/command added separately by caller).
# Third argument, if set, is the full prompt string (include trailing space if desired).
prompt_crontab_schedule() {
    local -n _out_cron="$1"
    local default_sched="$2"
    local prompt_msg="${3:-1.2. QUESTION: Define upgrade CRONTAB schedule: }"
    local line
    while true; do
        _prompt_read_line "${prompt_msg}" line || return 1
        line="$(_str_trim "$line")"
        if [ -z "$line" ]; then
            _out_cron="$default_sched"
            log INFO "Using default schedule: ${default_sched}"
            return 0
        fi
        # Five fields; allow step lists/ranges (e.g. */12, 1-5).
        if [[ "$line" =~ ^[-,0-9*/]+([[:space:]]+[-,0-9*/]+){4}$ ]]; then
            _out_cron="$line"
            return 0
        fi
        log WARN "Invalid schedule. Enter five cron time fields (e.g. 0 4 * * 6 or 0 */12 * * *)."
    done
}

# Interface must exist and support Wake-on-LAN per ethtool.
prompt_existing_wol_interface() {
    local -n _out_if="$1"
    local ifname check_wol
    while true; do
        _prompt_read_line "3.1. QUESTION: Enter interface name: " ifname || return 1
        ifname="$(_str_trim "$ifname")"
        if [ -z "$ifname" ]; then
            log WARN "Interface name cannot be empty."
            continue
        fi
        if ! ip link show "$ifname" &>/dev/null; then
            log WARN "Interface ${ifname} not found. Try: ip link"
            continue
        fi
        check_wol=$(ethtool "$ifname" 2>/dev/null | grep "Wake-on:" || true)
        if [ -z "$check_wol" ]; then
            log WARN "Wake-on-LAN is not reported for ${ifname}. Choose another interface."
            continue
        fi
        _out_if="$ifname"
        return 0
    done
}

# Optional locale/charset: empty allowed; caller applies defaults.
prompt_locale_field() {
    local prompt_text="$1"
    local -n _out_loc="$2"
    local line
    _prompt_read_line "$prompt_text" line || return 1
    line="$(_str_trim "$line")"
    _out_loc="$line"
}

# Single line, trimmed (empty allowed).
prompt_line_trimmed() {
    local prompt_text="$1"
    local -n _out_line="$2"
    _prompt_read_line "$prompt_text" _out_line || return 1
    _out_line="$(_str_trim "$_out_line")"
}

run_command() {
    COMMAND="$2"
    EXIT_ON_ERROR="$1"
    log INFO "Running command:"
    log TRACE "$COMMAND"
    $SHELL -c "$COMMAND"
    RESULT=$?
    if [[ "$RESULT" -ne "0" ]]; then
        log ERROR "Command failed."
        if [[ "$EXIT_ON_ERROR" -eq "1" ]]; then
            log ERROR "Exiting with status ${RESULT}."
            exit "$RESULT"
        else
            log WARN "Command failed. Returning with status ${RESULT}."
            return "$RESULT"
        fi
    fi
    log INFO "Command succeeded."
    return 0
}


setup_aws_environment() {
    local aws_profile
    aws_profile="$1"
    local aws_region
    aws_region="${2:-${AWS_REGION:-${AWS_DEFAULT_REGION:-"us-east-1"}}}"
    log INFO "Defining AWS environment variables for profile ${aws_profile} and region ${aws_region}..."
    local aws_access_key_id
    aws_access_key_id="$(aws configure get aws_access_key_id --profile "$aws_profile")"
    local aws_secret_access_key
    aws_secret_access_key="$(aws configure get aws_secret_access_key --profile "$aws_profile")"
    local aws_session_token
    aws_session_token="$(aws configure get aws_session_token --profile "$aws_profile")"

    log INFO "Exporting AWS environment variables for profile ${aws_profile} and region ${aws_region}..."
    export AWS_PROFILE="$aws_profile"
    export AWS_REGION="$aws_region"
    export AWS_ACCESS_KEY_ID="$aws_access_key_id"
    export AWS_SECRET_ACCESS_KEY="$aws_secret_access_key"
    export AWS_SESSION_TOKEN="$aws_session_token"
}

aws_sso_login() {
    log INFO "Checking if SSO login..."
    if [ -z "${AWS_PROFILE:-}" ] || [ -z "${SSO_LOGIN:-}" ] || ! command -v aws &>/dev/null ; then
        log WARN "Skipping SSO login as AWS_PROFILE or SSO_LOGIN is not set."
        return
    fi
    log INFO "Checking if the session is still valid for profile ${AWS_PROFILE}..."
    STS_COMMAND="AWS_ENDPOINT_URL_STS=\"https://sts.${AWS_REGION}.amazonaws.com\" aws sts --profile \"$AWS_PROFILE\" get-caller-identity"
    RESULT="$(eval "$STS_COMMAND" | jq -r '.Arn')"
    if [ -z "$RESULT" ]; then
        log INFO "Logging in with profile '$AWS_PROFILE'..."
        aws sso login --profile "$AWS_PROFILE" || {
            log "ERROR" "Profile ${AWS_PROFILE} does not exist."
            if [[ "${EXIT_ON_ERROR:-0}" -eq "1" ]]; then
                log ERROR "Exiting with status 1."
                exit 1
            else
                log WARN "SSO login failed. Returning with status 1."
                return 1
            fi
        }
    else
        log INFO "Session is still valid for profile ${AWS_PROFILE}."
    fi

    setup_aws_environment "$AWS_PROFILE" "$AWS_REGION"
    log INFO "SSO Login successfully performed..."
}


aws_mfa_login() {
    AWS_MFA_DURATION="${AWS_MFA_DURATION:-3600}"
    if [[ "${AWS_MFA_DURATION}" -lt "1000" ]]; then
        log "AWS_MFA_DURATION is less than 1000 seconds. This is not allowed. Setting to 1000 seconds."
        AWS_MFA_DURATION=1000
    fi
    log INFO "Refreshing MFA session..."
    if [ -z "${AWS_PROFILE:-}" ] || [ -z "${AWS_MFA_DEVICE:-}" ] || ! command -v aws-mfa &>/dev/null ; then
        log WARN "Skipping MFA session refreshing as AWS_PROFILE or AWS_MFA_DEVICE is not set. Check if command aws-mfa is available."
        if [[ "${EXIT_ON_ERROR:-0}" -eq "1" ]]; then
            log ERROR "Exiting with status 1."
            exit 1
        else
            log WARN "MFA session refreshing failed. Returning with status 1."
            return 1
        fi
    fi
    log INFO "Refreshing MFA session for profile ${AWS_PROFILE}..."
    COMMAND="aws-mfa --profile \"$AWS_PROFILE\" --device \"$AWS_MFA_DEVICE\" --duration \"${AWS_MFA_DURATION}\""
    if [[ "${AWS_MFA_FORCE:-0}" -eq "1" ]]; then
        COMMAND+=" --force"
    fi
    if [[ -n "${AWS_MFA_ROLE_SESSION_NAME:-}" ]] && [[ -n "${AWS_MFA_ASSUME_ROLE_ARN:-}" ]]; then
        COMMAND+=" --role-session-name \"$AWS_MFA_ROLE_SESSION_NAME\" --assume-role-arn \"$AWS_MFA_ASSUME_ROLE_ARN\""
    fi
    run_command 1 "$COMMAND"
    RESULT=$?
    if [[ "$RESULT" -ne "0" ]]; then
        log ERROR "MFA session refreshing failed."
        if [[ "${EXIT_ON_ERROR:-0}" -eq "1" ]]; then
            log ERROR "Exiting with status ${RESULT}."
            exit "$RESULT"
        else
            log WARN "MFA session refreshing failed. Returning with status ${RESULT}."
            return "$RESULT"
        fi
    fi

    setup_aws_environment "$AWS_PROFILE" "$AWS_REGION"
    log INFO "MFA session refreshed successfully..."
}
