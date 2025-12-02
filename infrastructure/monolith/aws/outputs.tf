output "cluster_id" {
  description = "ECS Cluster ID"
  value       = aws_ecs_cluster.monolith.id
}

output "cluster_name" {
  description = "ECS Cluster name"
  value       = aws_ecs_cluster.monolith.name
}

output "cluster_arn" {
  description = "ECS Cluster ARN"
  value       = aws_ecs_cluster.monolith.arn
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.monolith.dns_name
}

output "alb_url" {
  description = "URL to access the monolith service"
  value       = "http://${aws_lb.monolith.dns_name}"
}

output "health_url" {
  description = "Health check endpoint URL"
  value       = "http://${aws_lb.monolith.dns_name}/health"
}

output "ecr_repository_url" {
  description = "ECR repository URL for the monolith image"
  value       = aws_ecr_repository.monolith.repository_url
}

output "service_arn" {
  description = "ARN of the ECS service"
  value       = aws_ecs_service.monolith.id
}

output "task_definition_arn" {
  description = "ARN of the task definition"
  value       = aws_ecs_task_definition.monolith.arn
}

output "log_group_name" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.monolith.name
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "Cognito Client ID"
  value       = aws_cognito_user_pool_client.main.id
}