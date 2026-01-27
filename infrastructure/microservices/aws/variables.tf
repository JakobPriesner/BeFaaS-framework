variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "cpu" {
  description = "CPU units for the ECS tasks (256 = 0.25 vCPU, 512 = 0.5 vCPU, 1024 = 1 vCPU)"
  type        = number
  default     = 256
}

variable "memory" {
  description = "Memory in MB for the ECS tasks"
  type        = number
  default     = 512
}

# Auto-Scaling Configuration
variable "min_capacity" {
  description = "Minimum number of tasks for auto-scaling per service"
  type        = number
  default     = 2
}

variable "max_capacity" {
  description = "Maximum number of tasks for auto-scaling per service"
  type        = number
  default     = 100
}

variable "target_cpu_utilization" {
  description = "Target CPU utilization percentage for auto-scaling"
  type        = number
  default     = 70
}

variable "target_request_count" {
  description = "Target ALB requests per target per minute for auto-scaling (frontend-service only)"
  type        = number
  default     = 1500
}

variable "scale_out_cooldown" {
  description = "Scale-out cooldown period in seconds (Fast Response)"
  type        = number
  default     = 45
}

variable "scale_in_cooldown" {
  description = "Scale-in cooldown period in seconds (Slow Shrinkage) - Microservices: 180s"
  type        = number
  default     = 180
}