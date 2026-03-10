#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091,SC2034
set -euo pipefail


ENV=
AWS_PROFILE="default"
PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
TF_PROJECT_NAME="$(basename "$PROJECT_PATH")"
TF_PATH="${PROJECT_PATH}/terraform"
TF_PLAN_PATH="${TF_PATH}/plans"
TF_ENV_PATH="${TF_PATH}/environments"

# shellcheck source=${PROJECT_PATH}/deploy/utils.sh
{
    cd "$PROJECT_PATH" && source "${PROJECT_PATH}/deploy/utils.sh"
} || {
    echo "[ERROR] Runtime - cannot load utils path."
    exit 255
}

function run_terraform() {
    local action
    action="$1"
    local aws_profile
    aws_profile="$2"
    local tfvars_file
    tfvars_file="$3"
    local tailscale_api_key
    local tailscale_tailnet
    if [[ "${INPUT_TAILSCALE_PARAMS:-0}" -eq "1" ]]; then
        log "WARN" "Inputting Tailscale parameters manually..."
        printf "Enter the Tailscale API key: "
        read -r tailscale_api_key
        printf "Enter the Tailscale tailnet: "
        read -r tailscale_tailnet
    else
        log "INFO" "Using Tailscale parameters from environment variables..."
        tailscale_api_key="${TAILSCALE_API_KEY:-}"
        tailscale_tailnet="${TAILSCALE_TAILNET:-}"
    fi
    log "INFO" "Tailscale API key: ${tailscale_api_key}"
    log "INFO" "Tailscale tailnet: ${tailscale_tailnet}"
    chmod -R +rx "${PROJECT_PATH}"
    cd "${TF_PLAN_PATH}" && pwd
    if [[ "$action" == "init" ]]; then
        # Backend config is in tfvars; no -backend-config override
        RUN_COMMAND=$(cat <<EOM
terraform "$action" \
    -reconfigure \
    -backend-config="bucket=$TF_BACKEND_BUCKET" \
    -backend-config="key=$TF_BACKEND_KEY" \
    -backend-config="region=$AWS_REGION" \
    -backend-config="profile=$aws_profile" \
    -backend-config="encrypt=true" \
    -var="aws_profile=$aws_profile" \
    -var="aws_region=$AWS_REGION" \
    $(if [[ "$INPUT_TAILSCALE_PARAMS" == "1" ]] ; then echo "-var=\"tailscale_api_key=$tailscale_api_key\" -var=\"tailscale_tailnet=$tailscale_tailnet\"" ; fi)
EOM
        )
    else
        RUN_COMMAND=$(cat <<EOM
terraform "$(if [[ "$action" == "destroy" ]] ; then echo "-" ; fi)${action}" \
    $(if [[ "$action" != "plan" ]] ; then echo "-auto-approve" ; fi) -var-file="$tfvars_file" \
    -var="aws_profile=$aws_profile" \
    -var="aws_region=$AWS_REGION"
EOM
        )
    fi
    run_command 1 "$RUN_COMMAND"
    echo ""
}

ACTION="$1"
shift

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --env | --environment | -e)
            ENV="$2"
            shift 2
            ;;
        --tfvars-file)
            TF_VARS_FILE="$2"
            shift 2
            ;;
        --aws-profile | --profile | -p)
            AWS_PROFILE="$2"
            shift 2
            ;;
        --aws-region | --region | -r)
            AWS_REGION="$2"
            shift 2
            ;;
        --input-tailscale-params | -itp)
            INPUT_TAILSCALE_PARAMS="1"
            shift 1
            ;;
        *)
            shift
            ;;
    esac
done

if [ -z "$ENV" ]; then
    log "ERROR" "No environment was provided."
    exit 1
fi

# Always deploy from terraform/plans/ (plans/main.tf); backend config is in tfvars
TF_VARS_FILE="${TF_VARS_FILE:-"${TF_ENV_PATH}/config.${ENV}.tfvars"}"

if [[ ! -f "$TF_VARS_FILE" ]]; then
    log "ERROR" "Terraform var file not found: ${TF_VARS_FILE}"
    exit 1
fi

_TF_BACKEND_BUCKET=$(grep -E '\s*tf_backend_bucket\s*=' "$TF_VARS_FILE" | awk '{print $NF}' | tr -d '"')
_TF_BACKEND_KEY=$(grep -E '\s*tf_backend_key\s*=' "$TF_VARS_FILE" | awk '{print $NF}' | tr -d '"')
_DEFAULT_AWS_REGION=$(grep -E '\s*region\s*=' "$TF_VARS_FILE" | awk '{print $NF}' | tr -d '"')

if [[ -z "${AWS_REGION:-}" ]]; then
    export AWS_REGION="${_DEFAULT_AWS_REGION:-${AWS_REGION:-${AWS_DEFAULT_REGION:-"us-east-1"}}}"
    log "INFO" "Setting AWS_REGION to: ${AWS_REGION}"
fi

export TF_BACKEND_BUCKET="${_TF_BACKEND_BUCKET}"
export TF_BACKEND_KEY="${_TF_BACKEND_KEY}"

log "INFO" "Selecting Terraform workspace: ${TF_PROJECT_NAME}-${ENV}"

run_terraform init "$AWS_PROFILE" "$TF_VARS_FILE" || {
    log "ERROR" "There was an error while initializing Terraform (terraform/plans/main.tf)"
    exit 1
}

log "INFO" "Selecting/creating Terraform workspace: ${TF_PROJECT_NAME}-${ENV}"
run_command 1 "terraform workspace select -or-create=true \"${TF_PROJECT_NAME}-${ENV}\"" || {
    log "ERROR" "There was an error while selecting/creating Terraform workspace: ${TF_PROJECT_NAME}-${ENV}"
    exit 1
}

log "INFO" "Terraform workspace selected/created: ${TF_PROJECT_NAME}-${ENV}"

case "$ACTION" in
    init)
        log "INFO" "Terraform initialized..."
        ;;
    deploy|apply)
        log "INFO" "Deploying Terraform (terraform/plans/main.tf)"
        run_terraform apply "$AWS_PROFILE" "$TF_VARS_FILE" || {
            log "ERROR" "There was an error while deploying Terraform (terraform/plans/main.tf)"
            exit 1
        }
        ;;
    destroy)
        log "INFO" "Destroying Terraform (terraform/plans/main.tf)"
        run_terraform destroy "$AWS_PROFILE" "$TF_VARS_FILE" || {
            log "ERROR" "There was an error while destroying Terraform (terraform/plans/main.tf)"
            exit 1
        }
        ;;
    plan)
        log "INFO" "Planning Terraform (terraform/plans/main.tf)"
        run_terraform plan "$AWS_PROFILE" "$TF_VARS_FILE" || {
            log "ERROR" "There was an error while planning Terraform (terraform/plans/main.tf)"
            exit 1
        }
        ;;
    *)
        log "ERROR" "Action not supported."
        exit 1
        ;;
esac
