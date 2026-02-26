# full-stack-devops-homelab

End-to-end DevOps pipeline built from scratch on a self-hosted homelab from bare-metal VM provisioning to automated Kubernetes deployments with full CI/CD and monitoring.

## Overview

This project implements a production-style DevOps pipeline for a Django web application, running entirely on a self-managed Proxmox hypervisor. Every stage of the pipeline is automated: infrastructure provisioning, OS configuration, CI testing, container builds, image distribution, and rolling Kubernetes deployments triggered by a single `git push`.

The application (a Django Bakery app) is intentionally simple. The real focus of this project is the **infrastructure and automation** surrounding it.

## Pipeline Flow

Developer (PyCharm, Windows)
    │
    └── git push origin django-app
              │
              ▼
        GitLab (192.168.1.158)
        Webhook → HTTP POST
              │
              ▼
        Jenkins (192.168.1.192)
        ├── Spin up ephemeral MySQL container
        ├── Create Python 3.11 venv
        ├── pip install + migrate + test
        ├── docker build (tagged with git SHA)
        ├── docker save → .tar.gz
        └── scp → DevOps LXC (192.168.1.182)
              │
              ▼
        Ansible (DevOps LXC)
        ├── Distribute image to all K8s nodes
        ├── ctr import on each node
        ├── kubectl apply manifests
        └── kubectl rollout restart + status
              │
              ▼
        Kubernetes Cluster
        ├── initContainer: wait for MySQL → migrate
        ├── initContainer: collectstatic
        ├── django container (gunicorn :8000)
        └── nginx (:80 → proxy → :8000)
              │
              ▼
        App live at http://192.168.1.189:30914

## Tech Stack

Layer                       Tool

Hypervisor                  Proxmox VE 
IaC                         Terraform (bpg/proxmox provider v0.69.0) 
OS                          Rocky Linux 9 / Ubuntu 24.04 
Configuration Management    Ansible 2.18 
Source Control              GitLab CE 18.7.0 (self-hosted) 
CI/CD                       Jenkins 
Containerisation            Docker 
Orchestration               Kubernetes (kubeadm, 1 master + 3 workers) 
App Framework               Django + Gunicorn + Nginx 
Database                    MySQL 
Monitoring                  Prometheus + Grafana + cAdvisor + Node Exporter 

## Infrastructure

### VM Inventory

| Host                  | IP                  | Role                                       | Provisioned By |

| Proxmox               | 192.168.1.6         | Hypervisor                                 | Manual |
| GitLab VM             | 192.168.1.158       | Source control + webhooks                  | Terraform |
| Jenkins VM            | 192.168.1.192       | CI/CD server                               | Manual |
| DevOps LXC            | 192.168.1.182       | Ansible control node + CD intermediary     | Manual |
| K8s Master            | 192.168.1.189       | Kubernetes control plane                   | Terraform |
| K8s Worker 01         | 192.168.1.171       | Kubernetes worker                          | Terraform |
| K8s Worker 02         | 192.168.1.188       | Kubernetes worker                          | Terraform |
| K8s Worker 03         | 192.168.1.179       | Kubernetes worker                          | Terraform |
| Monitoring LXC        | 192.168.1.10        | Prometheus + Grafana stack                 | Manual |

### Base Template

All VMs are cloned from a custom Rocky Linux 9 Proxmox template (VM ID 8000):
- Minimal install, SSH key-only access
- cloud-init ready for scripted provisioning
- qemu-guest-agent enabled
- Safe to clone multiple times

## Repository Structure

full-stack-devops-homelab/
├── README.md
├── .gitignore
├── app/                          # Django Bakery application
│   ├── manage.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── web_app/
├── terraform/
│   ├── gitlab_vm/                # GitLab VM config (4 cores, 8GB RAM, 100GB)
│   │   ├── main.tf
│   │   ├── provider.tf
│   │   ├── variables.tf
│   │   └── terraform.tfvars.example
│   └── kubernetes_vm/            # Kubernetes VM config
│       ├── main.tf
│       ├── provider.tf
│       ├── variables.tf
│       └── terraform.tfvars.example
├── ansible/
│   ├── ansible.cfg
│   ├── inventory/
│   │   └── lab/
│   │       ├── all_hosts.ini
│   │       ├── gitlab.ini
│   │       ├── jenkins.ini
│   │       └── kubernetes.ini
│   ├── playbooks/
│   │   ├── gitlab.yml
│   │   ├── jenkins.yml
│   │   ├── kubernetes.yml
│   │   ├── deploy_app.yml
│   │   └── deploy_mysql.yml
│   └── roles/
│       ├── common/
│       ├── docker/
│       ├── jenkins/
│       ├── kube-master/
│       ├── kube-node/
│       └── ...
├── jenkins/
│   └── Jenkinsfile
├── kubernetes/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── mysql/
│       ├── mysql-deployment.yaml
│       └── mysql-service.yaml
├── monitoring/
│   ├── docker-compose.yml
│   └── prometheus/
│       └── prometheus.yml
└── docs/
    └── DevOps_Pipeline_Documentation.docx

## Key Design Decisions

**Terraform for VM provisioning** - GitLab and Kubernetes VMs are provisioned using the `bpg/proxmox` Terraform provider, cloning from a cloud-init-ready Rocky Linux 9 template. Each VM has its own isolated project folder and state file.

**Ansible as the CD intermediary** - The DevOps LXC acts as both the Ansible control node for infrastructure config and the deployment broker in the CD pipeline. Jenkins SCPs image tarballs here; Ansible then distributes them to Kubernetes nodes and triggers the rollout.

**No container registry** - Images are built on Jenkins, saved as `.tar.gz`, and distributed via `scp` + `ctr import`. This avoids registry infrastructure overhead while keeping the pipeline functional in an air-gapped home lab environment.

**Init containers for dependency ordering** - The Kubernetes deployment uses two init containers: one to wait for MySQL readiness and run migrations, one to run `collectstatic`. This ensures correct startup order without external orchestration.

**Git SHA image tagging** - Every Docker image is tagged with the git commit SHA, enabling precise traceability between a running pod and the exact code revision it was built from.

## Monitoring

The monitoring stack runs on a dedicated LXC (192.168.1.10) via Docker Compose:

- **Prometheus** - scrapes kubelet metrics from all 4 K8s nodes on port 10250
- **Grafana** - dashboard ID 315 for Kubernetes cluster visualisation
- **cAdvisor** - per-container resource metrics
- **Node Exporter** - host-level metrics

Grafana available at `http://192.168.1.10:3000`
Prometheus available at `http://192.168.1.10:9090`

## Security Notes

- Terraform authenticates to Proxmox via API token (not root password)
- `terraform.tfvars` files are gitignored - use the provided `.example` files as templates
- SSH key-only access across all managed hosts
- `insecure = true` in the Proxmox provider is intentional for a home lab with a self-signed cert - do not replicate in production

## Author

Built and documented by Eddie as a hands-on homelab project to gain practical experience with industry-standard DevOps tooling end-to-end.

