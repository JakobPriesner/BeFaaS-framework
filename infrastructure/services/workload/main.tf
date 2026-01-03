variable "validation_mode" {
  description = "Enable validation mode to log HTTP response details"
  type        = string
  default     = "false"
}

variable "auth_mode" {
  description = "Authentication mode for user preregistration"
  type        = string
  default     = "none"
}

data "terraform_remote_state" "exp" {
  backend = "local"

  config = {
    path = "${path.module}/../../experiment/terraform.tfstate"
  }
}

data "terraform_remote_state" "vpc" {
  backend = "local"

  config = {
    path = "${path.module}/../vpc/terraform.tfstate"
  }
}

data "terraform_remote_state" "redis" {
  backend = "local"

  config = {
    path = "${path.module}/../redisAws/terraform.tfstate"
  }
}

locals {
  project_name    = data.terraform_remote_state.exp.outputs.project_name
  deployment_id   = data.terraform_remote_state.exp.outputs.deployment_id
  default_subnet  = data.terraform_remote_state.vpc.outputs.default_subnet
  ssh_key_name    = data.terraform_remote_state.vpc.outputs.ssh_key_name
  security_groups = data.terraform_remote_state.vpc.outputs.security_groups
  ssh_private_key = data.terraform_remote_state.vpc.outputs.ssh_private_key
  redis_endpoint  = try(data.terraform_remote_state.redis.outputs.REDIS_ENDPOINT, "")
}

data "aws_ami" "ubuntu_lts" {
  most_recent = true
  name_regex  = "^ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-\\d+$"
  owners      = ["099720109477"]
}

resource "aws_instance" "workload" {
  ami                                  = data.aws_ami.ubuntu_lts.id
  instance_type                        = "t3a.medium"
  associate_public_ip_address          = true
  subnet_id                            = local.default_subnet
  key_name                             = local.ssh_key_name
  vpc_security_group_ids               = local.security_groups
  instance_initiated_shutdown_behavior = "terminate"

  tags = {
    Name = "${local.project_name}-workload"
  }

  provisioner "file" {
    connection {
      type        = "ssh"
      user        = "ubuntu"
      host        = self.public_ip
      private_key = local.ssh_private_key
      agent       = false
    }
    source      = "${path.module}/../../../artillery/image.tar.gz"
    destination = "/tmp/image.tar.gz"
  }

  provisioner "remote-exec" {
    connection {
      type        = "ssh"
      user        = "ubuntu"
      host        = self.public_ip
      private_key = local.ssh_private_key
      agent       = false
    }

    inline = [
      "sudo apt-get update",
      "sudo apt-get install -y docker.io",
      "sudo systemctl start docker",
      "sudo systemctl enable docker",
      "sudo docker load -i /tmp/image.tar.gz",
      "sudo docker run --rm -e BEFAAS_DEPLOYMENT_ID=${local.deployment_id} -e ARTILLERY_VALIDATION_MODE=${var.validation_mode} -e REDIS_ENDPOINT=${local.redis_endpoint} -e AUTH_MODE=${var.auth_mode} befaas/artillery"
    ]
  }
}
