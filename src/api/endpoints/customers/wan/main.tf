# The WAN-create worker: a Fargate Spot task that runs the whole pipeline
# (home -> constrain -> optimize -> validate) in one process and writes the
# customer's WAN JSON to the S3 store, or records a 422 reason. The dispatching
# Lambda starts this task (ecs:RunTask) on a customer create and on the carrier
# cascade. Async + Spot because a create can exceed API Gateway's ~29s cap and
# is fully retryable.

locals {
  store_bucket = data.terraform_remote_state.storage.outputs.bucket_name
}

resource "aws_ecr_repository" "optimizer" {
  name                 = "wan-graph-designer-optimizer"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

# Minimal VPC: one public subnet with egress, just for the create task.
resource "aws_vpc" "this" {
  cidr_block           = "10.80.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "wan-graph-designer" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.80.1.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "us-east-2a"
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "task" {
  name   = "wan-graph-designer-task"
  vpc_id = aws_vpc.this.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_cluster" "this" {
  name = "wan-graph-designer"
}

# Associate Fargate Spot (and on-demand) so run_task's FARGATE_SPOT capacity
# provider strategy is valid; without this, run_task fails and a WAN create hangs.
resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

resource "aws_cloudwatch_log_group" "optimizer" {
  name              = "/ecs/wan-graph-designer-optimizer"
  retention_in_days = 14
}

# Pull-image + logs role for the Fargate agent.
resource "aws_iam_role" "execution" {
  name = "wan-graph-designer-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The optimizer's own role: read inputs + write published/working graph JSON.
resource "aws_iam_role" "task" {
  name = "wan-graph-designer-optimizer"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task_s3" {
  name = "store-access"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        data.terraform_remote_state.storage.outputs.bucket_arn,
        "${data.terraform_remote_state.storage.outputs.bucket_arn}/*",
      ]
    }]
  })
}

resource "aws_ecs_task_definition" "optimizer" {
  family                   = "wan-graph-designer-optimizer"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "8192"
  memory                   = "32768"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "optimizer"
    image     = "${aws_ecr_repository.optimizer.repository_url}:latest"
    essential = true
    environment = [
      { name = "STORE_BUCKET", value = local.store_bucket },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.optimizer.name
        "awslogs-region"        = "us-east-2"
        "awslogs-stream-prefix" = "optimizer"
      }
    }
  }])
}
