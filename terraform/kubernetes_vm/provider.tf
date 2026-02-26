terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.69.0"
    }
  }
}

provider "proxmox" {
  endpoint = "https://192.168.1.6:8006/"
  api_token = "terraform@pve!terraform=${var.pm_api_token_secret}"
  insecure = true
}