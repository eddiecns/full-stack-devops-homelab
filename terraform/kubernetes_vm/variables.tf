variable "pm_api_token_secret" {
  type      = string
  sensitive = true
}

variable "ssh_public_key" {
  type = string
}

variable "ssh_password_hash" {
  description = "SHA-512 hashed password for user eddie"
  type        = string
  sensitive   = true
}