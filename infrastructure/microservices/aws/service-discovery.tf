# AWS Cloud Map Private DNS Namespace
resource "aws_service_discovery_private_dns_namespace" "microservices" {
  name        = "${var.deployment_id}.local"
  description = "Private DNS namespace for microservices"
  vpc         = var.vpc_id

  tags = {
    DeploymentId = var.deployment_id
    Architecture = "microservices"
  }
}

# Cloud Map Services for each microservice
resource "aws_service_discovery_service" "service" {
  for_each = local.services

  name = each.key

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.microservices.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    DeploymentId = var.deployment_id
    Service      = each.key
  }
}