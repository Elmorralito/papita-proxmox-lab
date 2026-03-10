#!/bin/bash

GREEN_TEXT='\033[0;32m'
RED_TEXT='\033[0;31m'
YELLOW_TEXT='\033[0;33m'
NC_TEXT='\033[0m'
BOLD_TEXT=$(tput bold)
NORMAL_TEXT=$(tput sgr0)

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
    elif [[ "$level" == "TRACE" ]]; then
        echo -e "$*"
        return
    fi
    echo -e "${color}$(date +"%Y-%m-%d %H:%M:%S") :: ${BOLD_TEXT}$(basename "$0")${NORMAL_TEXT} ${color}:: ${BOLD_TEXT}${level}${NORMAL_TEXT} ${color}:: $*${NC_TEXT}"
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
