variable "handler" {
  default = "index.lambdaHandler"
}

variable "memory_size" {
  default = 256
}

variable "timeout" {
  default = 60
}

variable "fn_env" {
  type    = map(string)
  default = {}
}

variable "edge_public_key" {
  description = "Ed25519 public key for edge authentication (base64 encoded)"
  type        = string
  default     = ""
}

variable "jwt_private_key" {
  description = "Ed25519 private key for JWT signing (base64-encoded PEM)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "jwt_public_key" {
  description = "Ed25519 public key for JWT verification (base64-encoded PEM)"
  type        = string
  default     = ""
}
