resource "proxmox_virtual_environment_vm" "k8s" {
  name      = "Kubernetes"
  node_name = "proxmox"

  clone {
    vm_id = 7000
    full  = true
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
  }

  disk {
    interface    = "scsi0"
    datastore_id = "local-zfs"
    size         = 100
    ssd          = true
  }

  network_device {
    bridge = "vmbr0"
    model  = "virtio"
  }

  agent {
    enabled = true
  }

  initialization {
    datastore_id = "local-zfs"

    user_account {
      username = "eddie"
      keys     = [var.ssh_public_key]
      password = var.ssh_password_hash
    }

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
  }

  started = true
  on_boot = true
}
