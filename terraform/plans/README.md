# Terraform plans — papita-proxmox-lab

Terraform in this repository provisions the **AWS side** of a hybrid Proxmox VE lab: shared **EFS** storage that on-prem PVE nodes reach over **Tailscale**, plus optional VPC networking and IAM for future AWS-hosted Tailscale routers. Proxmox cluster bootstrap, pfSense LAN routing, and Tailscale ACL maintenance are handled by Bash deploy scripts under `deploy/`, not by these plans today.

> **Status:** **`IN CONSTRUCTION`** — the root module (`main.tf`, `variables.tf`) and the `hybrid_proxmox_aws_cluster/` tree were removed pending a rebuild. Only this README is tracked under `terraform/plans/` at the moment. `deploy/terraform.sh` still expects the layout described below; `plan`, `apply`, and `destroy` will fail until `.tf` sources are restored or replaced.

---

## Role in the lab

```text
Workstation                          AWS (this Terraform stack)
deploy/toolkit.sh ──► deploy/terraform.sh
                              │
                              ▼
                    terraform/plans/main.tf  (S3 remote state)
                              │
                              └── hybrid_proxmox_aws_cluster/
                                      ├── aws/     EFS, VPC, SG, IAM
                                      └── tailscale/   placeholder (no resources yet)

On-prem (deploy/proxmox.sh, not Terraform)
  PVE nodes ──Tailscale (100.64.0.0/10)──► EFS NFS :2049
  pfSense   ──subnet router──────────────► 172.16.0.0/16 LAN
```

| Layer | Tooling | Responsibility |
| ----- | ------- | ---------------- |
| AWS shared storage | Terraform (`terraform/plans/`) | Encrypted EFS, mount targets, NFS security groups scoped to Tailscale CGNAT |
| PVE cluster ops | `deploy/proxmox.sh` | Node setup, WoL, temperature, cluster start/stop |
| Tailnet + LAN routing | `deploy/tailscale-pfsense-lan.sh` | Approve pfSense subnet routes, patch ACL grants, verify admin path to main PVE |
| Secrets / env config | `terraform/environments/*.tfvars`, `.env` | Per-environment values; **never committed** (see `.gitignore`) |

Operational runbooks: [`docs/TIPSNTRICKS.md`](../../docs/TIPSNTRICKS.md) (§9 Tailscale / pfSense LAN, EFS verify). Network diagram: [`docs/Diagrams-Network.png`](../../docs/Diagrams-Network.png).

---

## Directory layout

### Tracked today

```text
terraform/
├── environments/          # local only — config.{dev|prod|poc}.tfvars (gitignored)
└── plans/
    └── README.md          # this file
```

### Target layout (restore or reimplement)

```text
terraform/plans/
├── main.tf                          # Root entrypoint: S3 backend + hybrid module wiring
├── variables.tf                     # environment, owner, aws_*, plan_specific_aws_security_params
├── .terraform.lock.hcl              # Provider lock at plans root
└── hybrid_proxmox_aws_cluster/
    ├── main.tf                      # AWS + Tailscale providers; module aws { ... }
    ├── variables.tf / locals.tf / outputs.tf
    ├── .terraform.lock.hcl
    ├── aws/
    │   ├── network.tf               # Optional VPC/subnets; EFS security groups
    │   ├── efs.tf                   # EFS filesystem, access point (/pve), mount targets
    │   ├── iam.tf                   # Tailscale router EC2 role (SSM only)
    │   ├── main.tf / locals.tf / variables.tf / outputs.tf
    │   └── .terraform.lock.hcl
    └── tailscale/
        ├── main.tf                  # Placeholder — variables only, no resources yet
        ├── variables.tf
        └── README.md
```

The previous implementation is recoverable from git (commit before `refactor(terraform)!: remove hybrid AWS plans pending rebuild`, e.g. `c6f2ccc^`).

---

## How to run (when plans exist)

All Terraform operations run from the **repository root** via the deploy wrapper. Do not rely on ad-hoc `terraform` commands unless you mirror the same backend, workspace, and var-file paths.

### Via toolkit (recommended)

```bash
# AWS auth first (SSO/MFA/profile) — see deploy/toolkit.sh --help
./deploy/toolkit.sh terraform -e dev --terraform-action plan
./deploy/toolkit.sh terraform -e dev --terraform-action deploy   # same as apply
./deploy/toolkit.sh terraform -e dev --terraform-action destroy
```

### Direct wrapper

```bash
./deploy/terraform.sh plan   -e dev
./deploy/terraform.sh apply  -e dev
./deploy/terraform.sh destroy -e dev
```

### Wrapper flow (every action)

1. Load `terraform/environments/config.<env>.tfvars` (or `--tfvars-file`).
2. Parse `tf_backend_bucket`, `tf_backend_key`, and `region` from that file.
3. `cd terraform/plans` → `terraform init -reconfigure` with S3 backend flags.
4. Select or create workspace **`papita-proxmox-lab-<env>`** (project basename + environment).
5. Run `plan`, `apply` (`deploy` alias), or `destroy` with `-var-file=...` and `-auto-approve` on apply/destroy.

| Option | Purpose |
| ------ | ------- |
| `-e dev\|prod\|poc` | Required. Selects `config.<env>.tfvars`. |
| `--tfvars-file PATH` | Override var file path. |
| `-p, --aws-profile` | AWS profile for backend + provider (default: `default`). |
| `-r, --aws-region` | Override region; default from tfvars `region=` or `us-east-1`. |
| `-itp, --input-tailscale-params` | Prompt for Tailscale API key/tailnet during **init** only. |

Tailscale provider credentials for init (when wired in root module): `TAILSCALE_API_KEY`, `TAILSCALE_TAILNET`, or `-itp`. pfSense/PVE Tailscale automation uses the same variables via `.env` — see [`.env.example`](../../.env.example).

---

## Environment configuration (`terraform/environments/`)

Create one file per environment (all gitignored):

```text
terraform/environments/config.dev.tfvars
terraform/environments/config.prod.tfvars
terraform/environments/config.poc.tfvars
```

### Required keys (consumed by `deploy/terraform.sh`)

| Variable | Used by | Description |
| -------- | ------- | ----------- |
| `tf_backend_bucket` | `terraform init` | S3 bucket for remote state |
| `tf_backend_key` | `terraform init` | S3 object key for state file |
| `region` | init + provider | AWS region (also sets `AWS_REGION` when unset) |

### Root module variables (previous `variables.tf`)

| Variable | Required | Notes |
| -------- | -------- | ----- |
| `environment` | yes | `dev`, `prod`, or `poc` |
| `owner` | yes | Tagging / naming prefix |
| `aws_profile` | no | Default `default`; passed by wrapper |
| `aws_region` | yes | Passed by wrapper from tfvars / CLI |
| `plan_specific_aws_security_params` | yes | Map keyed by plan name; see below |

### Example skeleton (`config.dev.tfvars`)

```hcl
# Backend (read by deploy/terraform.sh before terraform init)
tf_backend_bucket = "your-org-terraform-state"
tf_backend_key    = "papita-proxmox-lab/dev/terraform.tfstate"
region            = "us-east-1"

# Root module
environment = "dev"
owner       = "your-handle"
aws_region  = "us-east-1"
aws_profile = "default"

plan_specific_aws_security_params = {
  hybrid_proxmox_aws_cluster = {
    # VPC: false = use existing VPC + subnet IDs; true = create VPC + private subnets
    aws_create_vpc           = false
    aws_vpc_id               = "vpc-xxxxxxxx"
    aws_private_subnet_ids   = ["subnet-aaa", "subnet-bbb", "subnet-ccc"]
    aws_private_subnet_cidrs = [] # used for SG rules when not creating VPC

    # Optional: create new VPC instead
    # aws_create_vpc         = true
    # aws_vpc_cidr           = "10.0.0.0/16"
    # aws_vpc_name           = "papita-dev"
    # availability_zones     = ["a", "b", "c"]

    # EFS (defaults matched previous root locals)
    aws_efs_root_path              = "/pve"
    aws_efs_performance_mode       = "generalPurpose"
    aws_efs_throughput_mode        = "elastic"
    aws_efs_transition_to_ia       = "AFTER_30_DAYS"
    aws_efs_backup_policy_status   = "ENABLED"
    aws_efs_posix_user_uid         = 1000
    aws_efs_posix_user_gid         = 1000
    aws_kms_key_arn                = null # null = module creates dedicated KMS key

    # NFS ingress on EFS SG — Tailscale CGNAT (lab default)
    tailscale_cidr_blocks = ["100.64.0.0/10"]
  }
}
```

Adjust subnet IDs, VPC, and CIDRs to your account. The lab’s on-prem LAN (`172.16.0.0/16`) is **not** an AWS VPC CIDR; it is advertised by pfSense on Tailscale, not by this Terraform stack.

---

## Module design (previous implementation)

### Root `main.tf`

- Terraform `>= 1.6.5, < 2.0.0`.
- **Backend:** `s3` (bucket/key/region/profile supplied at init by `deploy/terraform.sh`).
- **Providers (declared at root):** `aws ~> 5.28`, `tailscale ~> 0.13`, plus `archive`, `null`, `external`, `local`, `random`.
- **Single child module:** `hybrid_proxmox_aws_cluster` with plan version **`v2`**, pulling EFS/VPC parameters from `local.hybrid_proxmox_aws_cluster_params` (lookup in `plan_specific_aws_security_params`).

### `hybrid_proxmox_aws_cluster`

**Resource basename** (all AWS resource names):

```text
{plan_version}-{owner}-{project}-{environment}-{region}
```

Example: `v2-yourhandle-hybrid-proxmox-aws-cluster-dev-us-east-1` (`project` defaults to `hybrid-proxmox-aws-cluster`).

**Providers:** `aws` (region + profile + default tags), `tailscale` (API key + tailnet — for future resources).

**Child module `aws/`** — primary resources:

| Area | Resources | Behavior |
| ---- | --------- | -------- |
| Network | Optional VPC, private subnets, AZ validation | `aws_create_vpc = true` creates subnets; `false` uses `aws_vpc_id` + `aws_private_subnet_ids` |
| EFS | File system, mount targets, access point | Encrypted; optional dedicated KMS key; access point root **`/pve`** (POSIX uid/gid 1000 by default) |
| Security | `efs_tailscale_sg`, `efs_mount_target_sg` | NFS **2049** from `tailscale_cidr_blocks` (default `100.64.0.0/10`) and private subnet CIDRs |
| IAM | Tailscale router role + instance profile | **SSM only** (`AmazonSSMManagedInstanceCore`); no EFS IAM policies on PVE nodes |

**Outputs (aws submodule):** `vpc_id`, `private_subnet_ids`, `efs_file_system_id`, `efs_file_system_dns_name`, `efs_security_group_id`, etc.

**Child module `tailscale/`:** scaffold only (inputs: `plan_version`, `region`, `resource_basename`). No Tailscale resources were defined; ACL and route approval remain in `deploy/tailscale-pfsense-lan.sh`.

---

## Integration with on-prem PVE

After AWS EFS exists and PVE nodes complete setup (`deploy/proxmox.sh setup-node`):

1. **Every PVE node** joins Tailscale (steps 8–9 in `setup-pve-node.sh`) for the EFS data plane.
2. **pfSense** advertises `172.16.0.0/16` as a subnet router; remote admin targets the **main node** (default `172.16.0.101`), not worker UIs on the tailnet.
3. Mount EFS on each node over the tailnet (NFS to the EFS DNS name from Terraform outputs); security groups allow **2049** from `100.64.0.0/10`.

Verify from a tailnet client:

```bash
./deploy/tailscale-pfsense-lan.sh verify   # ping + HTTPS :8006 to main node
# On each PVE node: tailscale status; test NFS mount to EFS
```

See [`docs/TIPSNTRICKS.md`](../../docs/TIPSNTRICKS.md) §9 and the PVE setup manual at [`deploy/docs/setup-pve-node.usage.txt`](../../deploy/docs/setup-pve-node.usage.txt).

---

## Prerequisites

| Requirement | Notes |
| ----------- | ----- |
| Terraform CLI | `>= 1.6.5, < 2.0.0` (match previous lock files when restored) |
| AWS credentials | Profile or SSO/MFA via `deploy/toolkit.sh`; S3 backend bucket must exist and be writable |
| S3 state bucket | Created outside this repo; referenced only via tfvars |
| Local tfvars | One file per env under `terraform/environments/` |
| Tailscale API (init) | Only if root/hybrid providers require it during init; optional `-itp` |

---

## Conventions and safety

- **Never commit** `*.tfvars`, `.env`, or `.terraform/` — enforced in `.gitignore`.
- **Workspace isolation:** one workspace per environment (`papita-proxmox-lab-dev`, `-prod`, `-poc`); same S3 bucket may hold multiple keys if tfvars differ.
- **Destroy:** `./deploy/terraform.sh destroy -e <env>` runs with `-auto-approve`; EFS data loss is irreversible unless backups exist.
- **Provider locks:** restore `.terraform.lock.hcl` at plans root, hybrid module, and `aws/` submodule after re-adding code; run `terraform init -upgrade` only deliberately.

---

## Restoring or rewriting plans

1. Recover files from git history (parent of the removal commit) or redesign under `terraform/plans/`.
2. Ensure `main.tf` remains the **only** entrypoint referenced by `deploy/terraform.sh`.
3. Keep `plan_specific_aws_security_params.hybrid_proxmox_aws_cluster` shape compatible with the wrapper, or update both Terraform and `deploy/terraform.sh`.
4. Re-add provider lock files and run `./deploy/terraform.sh init -e dev` from a machine with valid AWS + tfvars.
5. Update this README when the module tree or variables change.

---

## Related paths

| Path | Purpose |
| ---- | ------- |
| [`deploy/terraform.sh`](../../deploy/terraform.sh) | Init, workspace, plan/apply/destroy |
| [`deploy/toolkit.sh`](../../deploy/toolkit.sh) | CLI entry; AWS auth + `terraform` action |
| [`deploy/usage.sh`](../../deploy/usage.sh) | `usage_terraform` help text |
| [`deploy/tailscale-pfsense-lan.sh`](../../deploy/tailscale-pfsense-lan.sh) | Tailscale ACL + pfSense LAN (not Terraform) |
| [`deploy/proxmox.sh`](../../deploy/proxmox.sh) | PVE node deploy and cluster helpers |
| [`.cursor/rules/repo-map.mdc`](../../.cursor/rules/repo-map.mdc) | Repository map (update when plans return) |
