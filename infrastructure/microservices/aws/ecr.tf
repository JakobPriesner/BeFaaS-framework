# ECR Repositories for each microservice
resource "aws_ecr_repository" "service" {
  for_each = local.services

  name                 = "${var.deployment_id}-${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = false
  }

  tags = {
    DeploymentId = var.deployment_id
    Service      = each.key
  }
}

# Lifecycle policy to keep only recent images
resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = local.services
  repository = aws_ecr_repository.service[each.key].name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 images"
        selection = {
          tagStatus     = "any"
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}