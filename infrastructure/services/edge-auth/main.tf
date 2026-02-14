# Edge-based Authentication Infrastructure
#
# Deploys CloudFront distribution with Lambda@Edge for token transformation.
# Lambda@Edge MUST be deployed in us-east-1 regardless of the main region.
#
# This module expects:
# - An origin endpoint (API Gateway or ALB)
# - Ed25519 key pair for token signing
# - Pre-built Lambda@Edge deployment package

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Primary provider (for CloudFront - which is global)
provider "aws" {
  region = var.aws_region
}

# Lambda@Edge MUST be in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

locals {
  project_name = var.project_name
}

# -----------------------------------------------------------------------------
# Lambda@Edge Function (MUST be in us-east-1)
# -----------------------------------------------------------------------------

# IAM Role for Lambda@Edge
resource "aws_iam_role" "edge_lambda" {
  provider = aws.us_east_1
  name     = "${local.project_name}-edge-auth-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = [
            "lambda.amazonaws.com",
            "edgelambda.amazonaws.com"
          ]
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project = local.project_name
  }
}

# Basic execution policy for Lambda@Edge
resource "aws_iam_role_policy_attachment" "edge_lambda_basic" {
  provider   = aws.us_east_1
  role       = aws_iam_role.edge_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda@Edge function
resource "aws_lambda_function" "edge_auth" {
  provider = aws.us_east_1

  function_name = "${local.project_name}-edge-auth"
  filename      = var.edge_lambda_zip_path
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  role          = aws_iam_role.edge_lambda.arn
  timeout       = 5 # Lambda@Edge max for viewer-request
  memory_size   = 128
  publish       = true # Lambda@Edge requires published version

  # Source code hash for updates
  source_code_hash = filebase64sha256(var.edge_lambda_zip_path)

  tags = {
    Project = local.project_name
  }
}

# -----------------------------------------------------------------------------
# CloudFront Distribution
# -----------------------------------------------------------------------------

resource "aws_cloudfront_distribution" "api" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${local.project_name} Edge Auth Distribution"
  price_class     = "PriceClass_100" # Use only North America and Europe edge locations

  # Origin configuration (API Gateway or ALB)
  origin {
    domain_name = var.origin_domain
    origin_id   = "origin"

    custom_origin_config {
      http_port              = var.origin_http_port
      https_port             = var.origin_https_port
      origin_protocol_policy = var.origin_protocol_policy
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    # Custom headers to identify requests from CloudFront
    custom_header {
      name  = "X-CloudFront-Secret"
      value = var.cloudfront_secret
    }
  }

  default_cache_behavior {
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD", "OPTIONS"]
    target_origin_id = "origin"

    # Disable caching for API requests
    # Note: Do NOT forward Host header - API Gateway returns 403 if Host doesn't match its domain
    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Content-Type", "Accept", "Origin", "Referer", "X-Requested-With", "X-BeFaaS-Edge-Processed", "X-BeFaaS-Edge-Subject"]

      cookies {
        forward = "all"
      }
    }

    viewer_protocol_policy = "https-only"
    min_ttl                = 0
    default_ttl            = 0
    max_ttl                = 0
    compress               = true

    # Lambda@Edge for auth transformation
    lambda_function_association {
      event_type   = "viewer-request"
      lambda_arn   = aws_lambda_function.edge_auth.qualified_arn
      include_body = true
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Project = local.project_name
  }

  # Wait for Lambda@Edge replication
  depends_on = [aws_lambda_function.edge_auth]
}

# -----------------------------------------------------------------------------
# SSM Parameters for Key Storage
# -----------------------------------------------------------------------------

# Store public key in SSM (for backends to retrieve)
resource "aws_ssm_parameter" "edge_public_key" {
  name  = "/${local.project_name}/edge-auth/public-key"
  type  = "String"
  value = var.ed25519_public_key

  tags = {
    Project = local.project_name
  }
}

# Store private key in SSM us-east-1 (for Lambda@Edge build)
resource "aws_ssm_parameter" "edge_private_key" {
  provider = aws.us_east_1
  name     = "/${local.project_name}/edge-auth/private-key"
  type     = "SecureString"
  value    = var.ed25519_private_key

  tags = {
    Project = local.project_name
  }
}