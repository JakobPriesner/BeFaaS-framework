terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  services = {
    "frontend-service" = {
      port           = 3000
      container_port = 3000
      cpu            = 256
      memory         = 512
      desired_count  = 2
    }
    "product-service" = {
      port           = 3001
      container_port = 3001
      cpu            = 256
      memory         = 512
      desired_count  = 2
    }
    "cart-service" = {
      port           = 3002
      container_port = 3002
      cpu            = 256
      memory         = 512
      desired_count  = 2
    }
    "order-service" = {
      port           = 3003
      container_port = 3003
      cpu            = 256
      memory         = 512
      desired_count  = 2
    }
    "content-service" = {
      port           = 3004
      container_port = 3004
      cpu            = 256
      memory         = 512
      desired_count  = 2
    }
  }
}

# ECS Cluster
resource "aws_ecs_cluster" "microservices" {
  name = "${var.deployment_id}-microservices"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    DeploymentId = var.deployment_id
    BuildId      = var.build_id
    Architecture = "microservices"
  }
}

# ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.deployment_id}-ecs-task-execution"

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
    DeploymentId = var.deployment_id
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role (for application permissions)
resource "aws_iam_role" "ecs_task" {
  name = "${var.deployment_id}-ecs-task"

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
    DeploymentId = var.deployment_id
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

# Security Group for ECS Tasks
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.deployment_id}-ecs-tasks"
  description = "Security group for microservices ECS tasks"
  vpc_id      = var.vpc_id

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
    Name         = "${var.deployment_id}-ecs-tasks"
    DeploymentId = var.deployment_id
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "microservices" {
  for_each = local.services

  name              = "/aws/${var.deployment_id}/${each.key}"
  retention_in_days = 7

  tags = {
    DeploymentId = var.deployment_id
    Service      = each.key
  }
}

# ECS Task Definitions
resource "aws_ecs_task_definition" "service" {
  for_each = local.services

  family                   = "${var.deployment_id}-${each.key}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${var.container_registry}/${each.key}:${var.build_id}"
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
          name  = "SERVICE_DISCOVERY_PROVIDER"
          value = "aws"
        },
        {
          name  = "CLOUDMAP_NAMESPACE_ID"
          value = aws_service_discovery_private_dns_namespace.microservices.id
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
          name  = "PORT"
          value = tostring(each.value.container_port)
        },
        {
          name  = "REDIS_URL"
          value = var.redis_url
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
    DeploymentId = var.deployment_id
    Service      = each.key
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
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
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
    DeploymentId = var.deployment_id
    Service      = each.key
  }
}