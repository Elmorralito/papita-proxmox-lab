#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
set -euo pipefail

ENV=
PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
LIBS_INPUT_PATH="${PROJECT_PATH}/libs"
LIBS_OUTPUT_PATH="${PROJECT_PATH}/dist"

# shellcheck source=${PROJECT_PATH}/deploy/utils.sh
{
    cd "${PROJECT_PATH}" && source "${PROJECT_PATH}/deploy/utils.sh"
} || {
    echo "[ERROR] Runtime - cannot load utils path."
    exit 255
}

# shellcheck source=${PROJECT_PATH}/deploy/usage.sh
source "${PROJECT_PATH}/deploy/usage.sh"

RAW_ARGS=("${@}")

ACTION="$1"
shift

aws_cli() {
  local cmd="aws $*"
  if [[ -n "${AWS_PROFILE:-}" ]]; then
    cmd+=" --profile ${AWS_PROFILE}"
  fi
  eval "${cmd}"
}

build() {
  log "INFO" "Starting build process using Poetry..."

  log "INFO" "Removing previous build artifacts..."
  rm -rf dist ./*.whl

  while IFS= read -r -d '' lib; do
    cd "$lib"
    local __package_name
    __package_name="$(basename "${lib}")"
    log "INFO" "Building the wheel of package ${__package_name} using Poetry..."
    poetry build -f wheel -o "${LIBS_OUTPUT_PATH}" -v || {
      log "ERROR" "Failed to build the wheel."
      exit 1
    }
    log "INFO" "Wheel of package ${__package_name} successfully built at ${LIBS_OUTPUT_PATH}"
  done <    <(find "${LIBS_INPUT_PATH}" -depth 1 -type d -print0)

  cd "${PROJECT_PATH}" && log "INFO" "Build process completed successfully."
}

devsync() {
  log "INFO" "Syncing development environment..."
  python -m pip install "${PROJECT_PATH}/dist/*.whl" --force-reinstall --no-cache
}

run_pytest() {
  log "INFO" "Running tests using pytest..."

  local __libs
  __libs="${PROJECT_PATH}/tests"
  while IFS= read -r -d '' lib; do
    local __package_name
    __package_name="$(basename "$lib")"
    __libs="${__libs}:${lib}/${__package_name}"
  done <    <(find "${LIBS_INPUT_PATH}" -depth 1 -type d -print0)

  log "INFO" "Setting PYTHONPATH to include libraries for testing."
  PYTHONPATH="${__libs}" poetry run pytest "${PROJECT_PATH}/tests" --cov=. || {
    log "ERROR" "Tests failed."
    exit 1
  }

  log "INFO" "All tests passed."
}

deploy() {
  log "INFO" "Starting deployment to '${ENV}' environment..."
  run_command 1 "${PROJECT_PATH}/deploy/terraform.sh ${TF_ACTION:-"deploy"} --env ${ENV} --profile ${AWS_PROFILE} --region ${AWS_REGION} ${RAW_ARGS[*]:1}"
}

pre_commit() {
  if [ -z "${PRE_COMMIT:-}" ]; then
    return
  fi

  log "INFO" "Running pre-commit"
  cd "${PROJECT_PATH}"
  pre-commit run --all-files &>/dev/null || {
    (eval "$(python -m poetry env activate)" && pre-commit run --all-files) || {
      log "ERROR" "The project did not pass the pre-commit checks."
      exit 1
    }
  }
}

# Main logic

_arg_n=1

# Parse arguments
while [[ "$#" -gt 0 ]]; do
  _arg_n="$(( _arg_n + 1 ))"
  case "$1" in
  --env | --environment | -e)
    ENV="$2"
    shift 2
    ;;
  --env-file | -ef)
    ENV_FILE="$2"
    shift 2
    ;;
  --aws-profile | --profile | -p)
    TEMP_AWS_PROFILE="$2"
    shift 2
    ;;
  --aws-region | --region | -r)
    TMP_AWS_REGION="$2"
    shift 2
    ;;
  --aws-sso-login | --aws-sso | -asl)
    TEMP_AWS_SSO_LOGIN="1"
    shift
    ;;
  --aws-mfa-login | --aws-mfa | -aml)
    TEMP_AWS_MFA_LOGIN="1"
    shift
    ;;
  --aws-mfa-device | -amdev)
    TEMP_AWS_MFA_DEVICE="$2"
    shift 2
    ;;
  --aws-mfa-duration | -amdr)
    TEMP_AWS_MFA_DURATION="$2"
    shift 2
    ;;
  --aws-mfa-role-session-name | -amrn)
    TEMP_AWS_MFA_ROLE_SESSION_NAME="$2"
    shift 2
    ;;
  --aws-mfa-assume-role-arn | -amara)
    TEMP_AWS_MFA_ASSUME_ROLE_ARN="$2"
    shift 2
    ;;
  --aws-mfa-force | -amf)
    TEMP_AWS_MFA_FORCE="1"
    shift
    ;;
  --libs-input-path | -lip)
    TEMP_LIBS_INPUT_PATH="$2"
    shift 2
    ;;
  --libs-output-path | -lop)
    TEMP_LIBS_OUTPUT_PATH="$2"
    shift 2
    ;;
  --pre-commit)
    TEMP_PRE_COMMIT="1"
    shift 1
    ;;
  --terraform-action | -ta)
    TEMP_TF_ACTION="$2"
    shift 2
    ;;
  --help | -h)
    usage_toolkit
    ;;
  *)
    shift
    ;;
  esac
done

if [[ -n "${ENV_FILE:-}" ]]; then
  ENV_FILE="$(realpath "${ENV_FILE}")"
  if [[ ! -f "${ENV_FILE}" ]]; then
    log "ERROR" "Environment file not found: ${ENV_FILE}"
    exit 1
  fi
  log "INFO" "Loading environment variables from ${ENV_FILE}"
  set -a
  source "${ENV_FILE}"
  set +a
  export AWS_PROFILE="${TEMP_AWS_PROFILE:-${AWS_PROFILE:-${AWS_PROFILE_DEFAULT:-}}}"
  export AWS_SSO_LOGIN="${TEMP_AWS_SSO_LOGIN:-${AWS_SSO_LOGIN:-0}}"
  export AWS_MFA_LOGIN="${TEMP_AWS_MFA_LOGIN:-${AWS_MFA_LOGIN:-0}}"
  export AWS_MFA_DEVICE="${TEMP_AWS_MFA_DEVICE:-${AWS_MFA_DEVICE:-${AWS_MFA_DEVICE_DEFAULT:-}}}"
  export AWS_MFA_DURATION="${TEMP_AWS_MFA_DURATION:-${AWS_MFA_DURATION:-${AWS_MFA_DURATION_DEFAULT:-3600}}}"
  export AWS_MFA_ROLE_SESSION_NAME="${TEMP_AWS_MFA_ROLE_SESSION_NAME:-${AWS_MFA_ROLE_SESSION_NAME:-${AWS_MFA_ROLE_SESSION_NAME_DEFAULT:-}}}"
  export AWS_MFA_ASSUME_ROLE_ARN="${TEMP_AWS_MFA_ASSUME_ROLE_ARN:-${AWS_MFA_ASSUME_ROLE_ARN:-${AWS_MFA_ASSUME_ROLE_ARN_DEFAULT:-}}}"
  export AWS_MFA_FORCE="${TEMP_AWS_MFA_FORCE:-${AWS_MFA_FORCE:-${AWS_MFA_FORCE_DEFAULT:-0}}}"
  export TF_ACTION="${TEMP_TF_ACTION:-${TF_ACTION:-"deploy"}}"
  export PRE_COMMIT="${TEMP_PRE_COMMIT:-${PRE_COMMIT:-0}}"
  export LIBS_INPUT_PATH="${TEMP_LIBS_INPUT_PATH:-${LIBS_INPUT_PATH:-}}"
  export LIBS_OUTPUT_PATH="${TEMP_LIBS_OUTPUT_PATH:-${LIBS_OUTPUT_PATH:-}}"
fi

# Validate inputs
if [[ -z "${ENV}" ]]; then
  log "ERROR" "Environment (-e) is required."
  usage_toolkit
fi

if [[ -z "${ACTION}" ]]; then
  log "ERROR" "Action at position 1 is required."
  usage_toolkit
fi

export AWS_REGION="${TMP_AWS_REGION:-${AWS_REGION:-${AWS_DEFAULT_REGION:-"us-east-1"}}}"
log "INFO" "Setting AWS_REGION to: ${AWS_REGION}"

if [[ "${AWS_SSO_LOGIN:-0}" -eq "1" ]]; then
  AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" aws_sso_login
elif [[ "${AWS_MFA_LOGIN:-0}" -eq "1" ]]; then
  export AWS_PROFILE="${AWS_PROFILE:-${AWS_PROFILE_DEFAULT:-}}"
  export AWS_MFA_DEVICE="${AWS_MFA_DEVICE:-"${AWS_MFA_DEVICE_DEFAULT:-}"}"
  export AWS_MFA_DURATION="${AWS_MFA_DURATION:-"${AWS_MFA_DURATION_DEFAULT:-3600}"}"
  export AWS_MFA_ROLE_SESSION_NAME="${AWS_MFA_ROLE_SESSION_NAME:-${AWS_MFA_ROLE_SESSION_NAME_DEFAULT:-}}"
  export AWS_MFA_ASSUME_ROLE_ARN="${AWS_MFA_ASSUME_ROLE_ARN:-${AWS_MFA_ASSUME_ROLE_ARN_DEFAULT:-}}"
  export AWS_MFA_FORCE="${AWS_MFA_FORCE:-"${AWS_MFA_FORCE_DEFAULT:-0}"}"

  log "INFO" "Logging into MFA with profile: $AWS_PROFILE"
  aws_mfa_login
elif [[ "${AWS_SSO_LOGIN:-0}" -eq "1" ]] && [[ "${AWS_MFA_LOGIN:-0}" -eq "1" ]]; then
  log "ERROR" "Choose only one AWS login method."
  usage_toolkit
else
  log "WARN" "Skipping AWS login as no AWS login method was provided."
fi

pre_commit

case "${ACTION}" in
build)
  build
  ;;
devsync)
  build
  devsync
  ;;
test)
  build
  run_pytest
  ;;
terraform | deploy )
  deploy
  ;;
none)
  log "INFO" "Doing noting..."
  ;;
*)
  log "ERROR" "Invalid action: '${ACTION}'"
  usage_toolkit
  ;;
esac
