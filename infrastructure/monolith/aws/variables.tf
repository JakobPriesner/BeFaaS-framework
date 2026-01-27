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
  description = "CPU units for the ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 512
}

variable "memory" {
  description = "Memory in MB for the ECS task"
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Initial number of monolith instances to run"
  type        = number
  default     = 3
}

# Auto-Scaling Configuration
variable "min_capacity" {
  description = "Minimum number of tasks for auto-scaling"
  type        = number
  default     = 2
}

variable "max_capacity" {
  description = "Maximum number of tasks for auto-scaling"
  type        = number
  default     = 100
}

variable "target_cpu_utilization" {
  description = "Target CPU utilization percentage for auto-scaling"
  type        = number
  default     = 70
}

variable "scale_out_cooldown" {
  description = "Scale-out cooldown period in seconds (Fast Response)"
  type        = number
  default     = 60
}

variable "scale_in_cooldown" {
  description = "Scale-in cooldown period in seconds (Slow Shrinkage) - Monolith: 300s"
  type        = number
  default     = 300
}