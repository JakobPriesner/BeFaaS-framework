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

# Use default VPC
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Reference Redis state
data "terraform_remote_state" "redis" {
  backend = "local"

  config = {
    path = "${path.module}/../../services/redisAws/terraform.tfstate"
  }
}

# Reference persistent Cognito pool
data "terraform_remote_state" "cognito" {
  backend = "local"

  config = {
    path = "${path.module}/../../services/cognito/terraform.tfstate"
  }
}

locals {
  project_name         = data.terraform_remote_state.exp.outputs.project_name
  subnet_ids           = data.aws_subnets.default.ids
  vpc_id               = data.aws_vpc.default.id
  redis_url            = data.terraform_remote_state.redis.outputs.REDIS_ENDPOINT
  cognito_user_pool_id = data.terraform_remote_state.cognito.outputs.cognito_user_pool_id
  cognito_client_id    = data.terraform_remote_state.cognito.outputs.cognito_client_id
  cognito_pool_arn     = data.terraform_remote_state.cognito.outputs.cognito_user_pool_arn
}


# ECR Repository for monolith
resource "aws_ecr_repository" "monolith" {
  name                 = "${local.project_name}-monolith"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # Allow destroy even with images

  image_scanning_configuration {
    scan_on_push = false
  }

  tags = {
    Project      = local.project_name
    Architecture = "monolith"
  }
}

# Lifecycle policy to keep only recent images
resource "aws_ecr_lifecycle_policy" "monolith" {
  repository = aws_ecr_repository.monolith.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ECS Cluster
resource "aws_ecs_cluster" "monolith" {
  name = "${local.project_name}-monolith"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Project      = local.project_name
    Architecture = "monolith"
  }
}

# ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.project_name}-monolith-task-execution"

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
  name = "${local.project_name}-monolith-task"

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

# IAM Policy for Cognito operations (needed for admin user confirmation)
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
        Resource = local.cognito_pool_arn
      }
    ]
  })
}

# Security Group for ALB
resource "aws_security_group" "alb" {
  name        = "${local.project_name}-monolith-alb"
  description = "Security group for Monolith ALB"
  vpc_id      = local.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${local.project_name}-monolith-alb"
    Project = local.project_name
  }
}

# Security Group for ECS Tasks
resource "aws_security_group" "ecs_tasks" {
  name        = "${local.project_name}-monolith-ecs"
  description = "Security group for monolith ECS tasks"
  vpc_id      = local.vpc_id

  # Allow traffic from ALB
  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # Allow all outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${local.project_name}-monolith-ecs"
    Project = local.project_name
  }
}

# Application Load Balancer
resource "aws_lb" "monolith" {
  name               = "${local.project_name}-monolith"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = local.subnet_ids

  enable_deletion_protection = false

  tags = {
    Project      = local.project_name
    Architecture = "monolith"
  }
}

# Target Group for Monolith
resource "aws_lb_target_group" "monolith" {
  name        = "${local.project_name}-monolith"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = local.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
  }

  # Reduced for faster cleanup
  deregistration_delay = 5

  tags = {
    Project = local.project_name
    Service = "monolith"
  }
}

# HTTP Listener
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.monolith.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.monolith.arn
  }

  tags = {
    Project = local.project_name
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "monolith" {
  name              = "/aws/ecs/${local.project_name}/monolith"
  retention_in_days = 7

  tags = {
    Project = local.project_name
    Service = "monolith"
  }
}

# ECS Task Definition
resource "aws_ecs_task_definition" "monolith" {
  family                   = "${local.project_name}-monolith"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "monolith"
      image     = "${aws_ecr_repository.monolith.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 3000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "PORT"
          value = "3000"
        },
        {
          name  = "NODE_ENV"
          value = "production"
        },
        {
          name  = "REDIS_ENDPOINT"
          value = local.redis_url
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "COGNITO_USER_POOL_ID"
          value = local.cognito_user_pool_id
        },
        {
          name  = "COGNITO_CLIENT_ID"
          value = local.cognito_client_id
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.monolith.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "node -e \"require('http').get('http://localhost:3000/health', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Project = local.project_name
    Service = "monolith"
  }
}

# ECS Service
resource "aws_ecs_service" "monolith" {
  name            = "monolith"
  cluster         = aws_ecs_cluster.monolith.id
  task_definition = aws_ecs_task_definition.monolith.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.monolith.arn
    container_name   = "monolith"
    container_port   = 3000
  }

  depends_on = [
    aws_lb_listener.http
  ]

  tags = {
    Project = local.project_name
    Service = "monolith"
  }

  # Ignore changes to desired_count as it's managed by auto-scaling
  lifecycle {
    ignore_changes = [desired_count]
  }
}

# Auto-Scaling Target
resource "aws_appautoscaling_target" "monolith" {
  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${aws_ecs_cluster.monolith.name}/${aws_ecs_service.monolith.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  depends_on = [aws_ecs_service.monolith]
}

# Auto-Scaling Policy - Target Tracking on CPU
resource "aws_appautoscaling_policy" "monolith_cpu" {
  name               = "${local.project_name}-monolith-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.monolith.resource_id
  scalable_dimension = aws_appautoscaling_target.monolith.scalable_dimension
  service_namespace  = aws_appautoscaling_target.monolith.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    target_value = var.target_cpu_utilization

    # Scale-out cooldown: 60s (Fast Response)
    scale_out_cooldown = var.scale_out_cooldown

    # Scale-in cooldown: 300s (Slow Shrinkage)
    # Verhältnis T_in/T_out = 300/60 = 5.0 (exceeds minimum of 3.0)
    scale_in_cooldown = var.scale_in_cooldown
  }
}