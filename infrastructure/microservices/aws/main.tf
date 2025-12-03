terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Reference experiment state for project name
data "terraform_remote_state" "exp" {
  backend = "local"

  config = {
    path = "${path.module}/../../experiment/terraform.tfstate"
  }
}

# Reference VPC state
data "terraform_remote_state" "vpc" {
  backend = "local"

  config = {
    path = "${path.module}/../../services/vpc/terraform.tfstate"
  }
}

# Reference Redis state
data "terraform_remote_state" "redis" {
  backend = "local"

  config = {
    path = "${path.module}/../../services/redisAws/terraform.tfstate"
  }
}

locals {
  project_name       = data.terraform_remote_state.exp.outputs.project_name
  subnet_ids         = data.terraform_remote_state.vpc.outputs.subnet_ids
  vpc_security_groups = data.terraform_remote_state.vpc.outputs.security_groups
  redis_url          = data.terraform_remote_state.redis.outputs.REDIS_ENDPOINT
}

# Get VPC ID from first subnet
data "aws_subnet" "first" {
  id = local.subnet_ids[0]
}

locals {
  vpc_id = data.aws_subnet.first.vpc_id

  services = {
    "frontend-service" = {
      port           = 3000
      container_port = 3000
      cpu            = 256
      memory         = 512
      desired_count  = 1
    }
    "product-service" = {
      port           = 3001
      container_port = 3001
      cpu            = 256
      memory         = 512
      desired_count  = 1
    }
    "cart-service" = {
      port           = 3002
      container_port = 3002
      cpu            = 256
      memory         = 512
      desired_count  = 1
    }
    "order-service" = {
      port           = 3003
      container_port = 3003
      cpu            = 256
      memory         = 512
      desired_count  = 1
    }
    "content-service" = {
      port           = 3004
      container_port = 3004
      cpu            = 256
      memory         = 512
      desired_count  = 1
    }
  }
}

# Cognito User Pool for authentication
resource "aws_cognito_user_pool" "main" {
  name = "${local.project_name}-microservices-user-pool"

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  tags = {
    Project      = local.project_name
    Architecture = "microservices"
  }
}

# Cognito User Pool Client
resource "aws_cognito_user_pool_client" "main" {
  name         = "${local.project_name}-microservices-client"
  user_pool_id = aws_cognito_user_pool.main.id

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_ADMIN_USER_PASSWORD_AUTH"
  ]

  generate_secret               = false
  prevent_user_existence_errors = "ENABLED"
}

# ECS Cluster
resource "aws_ecs_cluster" "microservices" {
  name = "${local.project_name}-microservices"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Project      = local.project_name
    Architecture = "microservices"
  }
}

# ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.project_name}-microservices-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project = local.project_name
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role (for application permissions)
resource "aws_iam_role" "ecs_task" {
  name = "${local.project_name}-microservices-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project = local.project_name
  }
}

# Allow tasks to use Cloud Map
resource "aws_iam_role_policy" "ecs_task_cloudmap" {
  name = "cloudmap-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "servicediscovery:RegisterInstance",
          "servicediscovery:DeregisterInstance",
          "servicediscovery:DiscoverInstances",
          "servicediscovery:Get*",
          "servicediscovery:List*"
        ]
        Resource = "*"
      }
    ]
  })
}

# IAM Policy for Cognito operations
resource "aws_iam_role_policy" "ecs_task_cognito" {
  name = "cognito-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "cognito-idp:AdminConfirmSignUp",
          "cognito-idp:AdminGetUser",
          "cognito-idp:AdminCreateUser",
          "cognito-idp:AdminSetUserPassword"
        ]
        Resource = aws_cognito_user_pool.main.arn
      }
    ]
  })
}

# Security Group for ECS Tasks
resource "aws_security_group" "ecs_tasks" {
  name        = "${local.project_name}-microservices-ecs"
  description = "Security group for microservices ECS tasks"
  vpc_id      = local.vpc_id

  # Allow all internal traffic within the security group
  ingress {
    from_port = 0
    to_port   = 65535
    protocol  = "tcp"
    self      = true
  }

  # Allow traffic from ALB
  ingress {
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${local.project_name}-microservices-ecs"
    Project = local.project_name
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "microservices" {
  for_each = local.services

  name              = "/aws/ecs/${local.project_name}/${each.key}"
  retention_in_days = 7

  tags = {
    Project = local.project_name
    Service = each.key
  }
}

# ECS Task Definitions
resource "aws_ecs_task_definition" "service" {
  for_each = local.services

  family                   = "${local.project_name}-${each.key}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${aws_ecr_repository.service[each.key].repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = each.value.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "SERVICE_NAME"
          value = each.key
        },
        {
          name  = "PORT"
          value = tostring(each.value.container_port)
        },
        {
          name  = "NODE_ENV"
          value = "production"
        },
        {
          name  = "CLOUDMAP_NAMESPACE"
          value = aws_service_discovery_private_dns_namespace.microservices.name
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "REDIS_URL"
          value = local.redis_url
        },
        {
          name  = "COGNITO_USER_POOL_ID"
          value = aws_cognito_user_pool.main.id
        },
        {
          name  = "COGNITO_CLIENT_ID"
          value = aws_cognito_user_pool_client.main.id
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.microservices[each.key].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${each.value.container_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Project = local.project_name
    Service = each.key
  }
}

# ECS Services
resource "aws_ecs_service" "service" {
  for_each = local.services

  name            = each.key
  cluster         = aws_ecs_cluster.microservices.id
  task_definition = aws_ecs_task_definition.service[each.key].arn
  desired_count   = each.value.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.subnet_ids
    security_groups  = concat([aws_security_group.ecs_tasks.id], local.vpc_security_groups)
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.service[each.key].arn
  }

  # Load balancer configuration only for frontend service
  dynamic "load_balancer" {
    for_each = each.key == "frontend-service" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.frontend.arn
      container_name   = each.key
      container_port   = each.value.container_port
    }
  }

  depends_on = [
    aws_lb_listener.http,
    aws_service_discovery_service.service
  ]

  tags = {
    Project = local.project_name
    Service = each.key
  }
}