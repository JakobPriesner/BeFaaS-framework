output "cluster_id" {
  description = "ECS Cluster ID"
  value       = aws_ecs_cluster.microservices.id
}

output "cluster_name" {
  description = "ECS Cluster name"
  value       = aws_ecs_cluster.microservices.name
}

output "cluster_arn" {
  description = "ECS Cluster ARN"
  value       = aws_ecs_cluster.microservices.arn
}

output "cloudmap_namespace_id" {
  description = "Cloud Map namespace ID"
  value       = aws_service_discovery_private_dns_namespace.microservices.id
}

output "cloudmap_namespace_name" {
  description = "Cloud Map namespace name"
  value       = aws_service_discovery_private_dns_namespace.microservices.name
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.microservices.dns_name
}

output "alb_url" {
  description = "URL to access the frontend service"
  value       = "http://${aws_lb.microservices.dns_name}"
}

output "health_url" {
  description = "Health check URL for the frontend service"
  value       = "http://${aws_lb.microservices.dns_name}/health"
}

output "ecr_repositories" {
  description = "ECR repository URLs for each service"
  value = {
    for service_name, repo in aws_ecr_repository.service : service_name => repo.repository_url
  }
}

output "service_arns" {
  description = "ARNs of all ECS services"
  value = {
    for service_name, service in aws_ecs_service.service : service_name => service.id
  }
}

output "cloudmap_service_arns" {
  description = "ARNs of all Cloud Map services"
  value = {
    for service_name, service in aws_service_discovery_service.service : service_name => service.arn
  }
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "Cognito User Pool Client ID"
  value       = aws_cognito_user_pool_client.main.id
}