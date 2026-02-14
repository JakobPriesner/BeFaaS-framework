# Edge-auth module variables

variable "aws_region" {
  description = "Primary AWS region (CloudFront is global, but state is stored here)"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

# Origin configuration
variable "origin_domain" {
  description = "Domain name of the origin (API Gateway or ALB)"
  type        = string
}

variable "origin_http_port" {
  description = "HTTP port on the origin"
  type        = number
  default     = 80
}

variable "origin_https_port" {
  description = "HTTPS port on the origin"
  type        = number
  default     = 443
}

variable "origin_protocol_policy" {
  description = "Protocol policy for origin requests (http-only, https-only, match-viewer)"
  type        = string
  default     = "https-only"
}

# Lambda@Edge configuration
variable "edge_lambda_zip_path" {
  description = "Path to the Lambda@Edge deployment package (zip file)"
  type        = string
}

# Ed25519 key configuration
variable "ed25519_private_key" {
  description = "Ed25519 private key in base64 DER format"
  type        = string
  sensitive   = true
}

variable "ed25519_public_key" {
  description = "Ed25519 public key in base64 DER format"
  type        = string
}

# Security
variable "cloudfront_secret" {
  description = "Secret header value to identify requests from CloudFront"
  type        = string
  default     = ""
  sensitive   = true
}