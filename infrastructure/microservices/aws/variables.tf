variable "deployment_id" {
  description = "Unique identifier for this deployment"
  type        = string
}

variable "build_id" {
  description = "Build identifier for container images"
  type        = string
}

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = "VPC ID where resources will be deployed"
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for the ALB"
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "container_registry" {
  description = "Container registry URL (ECR repository URL)"
  type        = string
}

variable "redis_url" {
  description = "Redis connection URL for cart service"
  type        = string
}