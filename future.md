# Future DevOps Subagent Matrix (`future.md`)

This roadmap defines the next wave of specialized, tool-scoped worker subagents for the **Zero-Inference Micro-Task Decomposition & Subagent Orchestrator**, mapped directly to the official **[roadmap.sh DevOps Roadmap](https://roadmap.sh/devops)**.

In accordance with our core architectural invariants:
* **Strict Tool Scoping**: Every subagent role is restricted to **at most 1–2 explicit tools** (`MAX_TOOLS_PER_SUBAGENT = 2`).
* **Zero-Inference Execution**: Ephemeral, single-turn prompts with bounded payloads, eliminating context drift on 7B–9B models (Qwen 2.5/3.5, Gemma 2/3, Llama 3.x).
* **Deterministic Verification**: No LLM self-reflection; validation occurs via CLI exit codes, JSON Schema validators, dry-run flags, and regex filters.

---

## Roadmap Status Overview

| Phase | Focus Area | Status | Subagents Included |
| :--- | :--- | :--- | :--- |
| **Phase 1 (Current)** | Core Containers, Orchestration, & VCS | **Implemented** | `docker`, `kubectl`, `gh`, `command_runner`, `code_editor`, `parser`, `validator` |
| **Phase 2 (Immediate Next)** | IaC, Kubernetes Packaging, & GitOps | **Up Next** | `terraform`, `helm`, `kustomize`, `argocd`, `ansible` |
| **Phase 3 (Mid-Term)** | Cloud CLIs, CI/CD, & Secret Management | Planned | `aws`, `az`, `gcloud`, `vault`, `sops`, `git` |
| **Phase 4 (Advanced)** | Observability, Security Scanning, & Mesh | Planned | `trivy`, `cosign`, `promtool`, `grafana`, `istioctl`, `cmctl` |

---

## Detailed Subagent Specifications (roadmap.sh Mapped)

### Phase 2: IaC, Packaging, & GitOps Delivery

#### 1. `terraform` (Infrastructure as Code)
* **Roadmap.sh Node**: *Infrastructure as Code > Terraform / OpenTofu*
* **Role ID**: `terraform` / `tofu`
* **Toolset Scope (<= 2 tools)**:
  1. `terraform_plan`: Executes `terraform plan -detailed-exitcode -out=tfplan` and `terraform show -json tfplan`.
  2. `terraform_apply`: Executes targeted `terraform apply -auto-approve [target]` or `terraform fmt -check`.
* **Input Payload**: Bounded target module path, variable inputs (`inputs: {var_file: "..."}`), state lock timeout.
* **Deterministic Verification**:
  - `terraform plan` exit code (`0` = no changes, `2` = changes present and valid, `1` = error).
  - JSON validation of `terraform show -json` against resource drift schema.

#### 2. `helm` (Kubernetes Package Management)
* **Roadmap.sh Node**: *Container Orchestration > Helm*
* **Role ID**: `helm`
* **Toolset Scope (<= 2 tools)**:
  1. `helm_template_lint`: Executes `helm lint <chart>` and `helm template <release> <chart> -f <values>`.
  2. `helm_upgrade_diff`: Executes `helm diff upgrade` or `helm upgrade --dry-run=server --install`.
* **Input Payload**: Chart path, release name, values override file or key-value dictionary, namespace.
* **Deterministic Verification**: Exit code `0`, YAML output parsed through `kubectl_manifest_dry_run`.

#### 3. `kustomize` (Declarative Overlay Engine)
* **Roadmap.sh Node**: *Container Orchestration > Kustomize*
* **Role ID**: `kustomize`
* **Toolset Scope (<= 2 tools)**:
  1. `kustomize_build`: Executes `kustomize build <overlay_path>`.
  2. `kustomize_edit`: Executes bounded mutations (e.g., `kustomize edit set image`, `set namespace`).
* **Input Payload**: Overlay directory path (`overlays/prod`), target image/tag replacements.
* **Deterministic Verification**: Exit code `0`, multi-document YAML parse test.

#### 4. `argocd` (Declarative Continuous Delivery & GitOps)
* **Roadmap.sh Node**: *CI/CD > GitOps > ArgoCD*
* **Role ID**: `argocd`
* **Toolset Scope (<= 2 tools)**:
  1. `argocd_app_sync`: Executes `argocd app sync <app_name> --prune --timeout <sec>`.
  2. `argocd_app_get`: Executes `argocd app get <app_name> -o json`.
* **Input Payload**: App name, target revision/commit hash, server address.
* **Deterministic Verification**: JSON Schema check ensuring `status.sync.status == "Synced"` and `status.health.status == "Healthy"`.

#### 5. `ansible` (Configuration Management & Node Provisioning)
* **Roadmap.sh Node**: *Configuration Management > Ansible*
* **Role ID**: `ansible`
* **Toolset Scope (<= 2 tools)**:
  1. `ansible_playbook_check`: Executes `ansible-playbook --syntax-check` and `--check --diff`.
  2. `ansible_playbook_run`: Executes targeted playbook execution with `--limit <host_pattern>`.
* **Input Payload**: Playbook path, inventory file, extra-vars JSON payload.
* **Deterministic Verification**: Exit code `0`, failure recap check (`failed=0`, `unreachable=0`).

---

### Phase 3: Cloud CLIs, CI/CD, & Secret Management

#### 6. `aws` (AWS Cloud Operator)
* **Roadmap.sh Node**: *Cloud Providers > AWS*
* **Role ID**: `aws`
* **Toolset Scope (<= 2 tools)**:
  1. `aws_cli_exec`: Executes scoped AWS CLI commands (`aws ecs describe-services`, `aws s3 sync`, `aws sts get-caller-identity`).
  2. `aws_json_query`: Executes AWS commands with `--query` and `--output json`.
* **Input Payload**: Command string, target AWS region, profile.
* **Deterministic Verification**: JSON Schema validation on stdout, exit code `0`.

#### 7. `az` (Azure Cloud Operator)
* **Roadmap.sh Node**: *Cloud Providers > Azure*
* **Role ID**: `az`
* **Toolset Scope (<= 2 tools)**:
  1. `az_cli_exec`: Executes bounded Azure CLI commands (`az aks get-credentials`, `az acr build`).
  2. `az_json_query`: Executes commands with `--query` and `-o json`.
* **Input Payload**: Subscription ID, resource group, command string.
* **Deterministic Verification**: Exit code `0`, JSON parsing.

#### 8. `gcloud` (Google Cloud SDK Operator)
* **Roadmap.sh Node**: *Cloud Providers > Google Cloud*
* **Role ID**: `gcloud`
* **Toolset Scope (<= 2 tools)**:
  1. `gcloud_cli_exec`: Executes scoped commands (`gcloud container clusters get-credentials`, `gcloud builds submit`).
  2. `gcloud_json_query`: Executes commands with `--format="json"`.
* **Input Payload**: Project ID, region/zone, command string.
* **Deterministic Verification**: Exit code `0`, JSON schema verification.

#### 9. `vault` (Secret Lifecycle & PKI Operator)
* **Roadmap.sh Node**: *Secret Management > HashiCorp Vault*
* **Role ID**: `vault`
* **Toolset Scope (<= 2 tools)**:
  1. `vault_kv_read`: Executes `vault kv get -format=json <path>`.
  2. `vault_token_renew`: Executes `vault token renew` or `vault status -format=json`.
* **Input Payload**: Secret path, namespace, field filters.
* **Deterministic Verification**: JSON Schema check, strict masking of sensitive fields from task history.

#### 10. `sops` (Encrypted File Secrets Management)
* **Roadmap.sh Node**: *Secret Management > SOPS*
* **Role ID**: `sops`
* **Toolset Scope (<= 2 tools)**:
  1. `sops_encrypt`: Executes `sops --encrypt --in-place <file>`.
  2. `sops_decrypt_validate`: Executes `sops --decrypt <file>` piped to schema linter (in-memory).
* **Input Payload**: Target file path, KMS/Age key recipient flags.
* **Deterministic Verification**: File header verification (`sops` metadata block present), exit code `0`.

#### 11. `git` (Core Version Control & Branch Operator)
* **Roadmap.sh Node**: *Version Control Systems > Git*
* **Role ID**: `git`
* **Toolset Scope (<= 2 tools)**:
  1. `git_status_diff`: Executes `git status --porcelain`, `git diff --stat`, or `git log -n 1 --format=json`.
  2. `git_branch_commit`: Executes atomic, explicit branch creation, checkout, or commit commands.
* **Input Payload**: Repository path, commit message or target branch name.
* **Deterministic Verification**: Exit code `0`, clean working tree check.

---

### Phase 4: Observability, DevSecOps Scanning, & Service Mesh

#### 12. `trivy` (Container & IaC Vulnerability Scanner)
* **Roadmap.sh Node**: *DevSecOps > Vulnerability Scanning > Trivy*
* **Role ID**: `trivy`
* **Toolset Scope (<= 2 tools)**:
  1. `trivy_scan_image`: Executes `trivy image --severity HIGH,CRITICAL --format json -o report.json <image>`.
  2. `trivy_scan_fs`: Executes `trivy fs --exit-code 1 --severity CRITICAL <path>`.
* **Input Payload**: Image name, severity thresholds, scan target path.
* **Deterministic Verification**: JSON report parsing, assertion that `CRITICAL` count == 0.

#### 13. `checkov` (Static Code Analysis for IaC)
* **Roadmap.sh Node**: *DevSecOps > IaC Security > Checkov*
* **Role ID**: `checkov`
* **Toolset Scope (<= 2 tools)**:
  1. `checkov_scan_directory`: Executes `checkov -d <dir> --framework terraform,kubernetes -o json`.
  2. `checkov_scan_file`: Executes `checkov -f <file> -o json`.
* **Input Payload**: Target directory or file path.
* **Deterministic Verification**: Exit code `0` or JSON failure recap inspection.

#### 14. `cosign` (Supply Chain & Container Signing)
* **Roadmap.sh Node**: *DevSecOps > Supply Chain Security > Cosign*
* **Role ID**: `cosign`
* **Toolset Scope (<= 2 tools)**:
  1. `cosign_verify`: Executes `cosign verify --key <key_path> <image_digest>`.
  2. `cosign_sign`: Executes `cosign sign --key <key_path> <image_digest>`.
* **Input Payload**: Image reference with digest, public key or KMS URI.
* **Deterministic Verification**: Exit code `0`, verification payload JSON parsing.

#### 15. `promtool` (Prometheus Metrics & Rule Verification)
* **Roadmap.sh Node**: *Monitoring & Observability > Prometheus*
* **Role ID**: `promtool`
* **Toolset Scope (<= 2 tools)**:
  1. `promtool_check_rules`: Executes `promtool check rules <alerts.yaml>`.
  2. `promtool_test_rules`: Executes `promtool test rules <unit_tests.yaml>`.
* **Input Payload**: Alert rule YAML path, Prometheus test definition file.
* **Deterministic Verification**: Exit code `0`, output regex matching `SUCCESS`.

#### 16. `grafana` (Dashboard & Alert Rule Operator)
* **Roadmap.sh Node**: *Monitoring & Observability > Grafana*
* **Role ID**: `grafana`
* **Toolset Scope (<= 2 tools)**:
  1. `grafana_dashboard_lint`: Validates dashboard JSON against Grafana schema.
  2. `grafana_api_sync`: Pushes dashboard JSON to Grafana API via HTTP POST.
* **Input Payload**: Dashboard JSON file path, folder UID.
* **Deterministic Verification**: HTTP 200 response with `status: "success"`.

#### 17. `istioctl` (Service Mesh Operator)
* **Roadmap.sh Node**: *Networking > Service Mesh > Istio*
* **Role ID**: `istioctl`
* **Toolset Scope (<= 2 tools)**:
  1. `istioctl_analyze`: Executes `istioctl analyze -n <namespace> -o json`.
  2. `istioctl_proxy_status`: Executes `istioctl proxy-status <pod_name>`.
* **Input Payload**: Target namespace, manifest files, pod identifier.
* **Deterministic Verification**: JSON validation asserting zero error messages.

#### 18. `cmctl` (Certificate Management CLI)
* **Roadmap.sh Node**: *Networking > SSL/TLS > Cert-Manager*
* **Role ID**: `cmctl`
* **Toolset Scope (<= 2 tools)**:
  1. `cmctl_check_api`: Executes `cmctl check api --wait <timeout>`.
  2. `cmctl_status_cert`: Executes `cmctl status certificate <cert_name> -n <ns>`.
* **Input Payload**: Certificate name, namespace, timeout seconds.
* **Deterministic Verification**: Exit code `0`, assertion that certificate status is `Ready`.

---

## Architectural Implementation Plan for Next Subagents

Whenever adding any of the subagents above to the repository:
1. **Declare Role Enum**: Add the new subagent key to `SubagentRole` in `planner/schema.py` and regenerate `planner/plan.schema.json`.
2. **Author Scoped Subagent**: Create `subagents/<tool>_subagent.py` inheriting from `BaseSubagent`, enforcing `<= 2` tool definitions and single-responsibility system prompt.
3. **Export & Register**: Export in `subagents/__init__.py` and register in `OrchestratorEngine.subagents` in `orchestrator/engine.py`.
4. **Add Deterministic Validator**: If the tool outputs structured JSON, register its schema check in `_verify_task_output`.
5. **Unit & Integration Tests**: Add automated lifecycle tests in `tests/test_orchestrator_suite.py` with mock command execution.
