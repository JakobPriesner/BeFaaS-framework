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
  project_name    = data.terraform_remote_state.exp.outputs.project_name
  subnet_ids      = data.terraform_remote_state.vpc.outputs.subnet_ids
  security_groups = data.terraform_remote_state.vpc.outputs.security_groups
  redis_url       = data.terraform_remote_state.redis.outputs.REDIS_ENDPOINT
}

# Cognito User Pool for authentication
resource "aws_cognito_user_pool" "main" {
  name = "${local.project_name}-monolith-user-pool"

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
    Architecture = "monolith"
  }
}

# Cognito User Pool Client
resource "aws_cognito_user_pool_client" "main" {
  name         = "${local.project_name}-monolith-client"
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

# Get VPC ID from subnets
data "aws_subnet" "first" {
  id = local.subnet_ids[0]
}

locals {
  vpc_id = data.aws_subnet.first.vpc_id
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
        Resource = aws_cognito_user_pool.main.arn
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

  deregistration_delay = 30

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
          name  = "REDIS_URL"
          value = local.redis_url
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
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
    security_groups  = concat([aws_security_group.ecs_tasks.id], local.security_groups)
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
}