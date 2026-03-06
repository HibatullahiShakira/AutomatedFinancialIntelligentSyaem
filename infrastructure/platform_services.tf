locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_s3_bucket" "event_store" {
  bucket = "${local.name_prefix}-event-store"
}

resource "aws_s3_bucket" "ml_artifacts" {
  bucket = "${local.name_prefix}-ml-artifacts"
}

resource "aws_s3_bucket" "documents" {
  bucket = "${local.name_prefix}-documents"
}

resource "aws_sqs_queue" "events_dlq" {
  name = "${local.name_prefix}-events-dlq.fifo"

  fifo_queue                  = true
  content_based_deduplication = true
}

resource "aws_sqs_queue" "events" {
  name = "${local.name_prefix}-events.fifo"

  fifo_queue                  = true
  content_based_deduplication = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.events_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_ecr_repository" "api" {
  name = "${local.name_prefix}-api"
}

resource "aws_ecr_repository" "worker" {
  name = "${local.name_prefix}-worker"
}

resource "aws_secretsmanager_secret" "app" {
  name = "${local.name_prefix}-app-secrets"
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL = "postgresql://${var.db_username}:${var.db_password}@example:5432/${var.db_name}"
    REDIS_URL    = "redis://example:6379/0"
  })
}

resource "aws_db_subnet_group" "main" {
  count      = var.enable_stateful_resources ? 1 : 0
  name       = "${local.name_prefix}-db-subnets"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  count = var.enable_stateful_resources ? 1 : 0

  identifier             = "${local.name_prefix}-postgres"
  allocated_storage      = 20
  engine                 = "postgres"
  engine_version         = "15"
  instance_class         = "db.t4g.micro"
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main[0].name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  skip_final_snapshot    = true
  multi_az               = var.multi_az_enabled
}

resource "aws_elasticache_subnet_group" "main" {
  count      = var.enable_stateful_resources ? 1 : 0
  name       = "${local.name_prefix}-redis-subnets"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "main" {
  count = var.enable_stateful_resources ? 1 : 0

  replication_group_id       = "${replace(local.name_prefix, "-", "")}-redis"
  description                = "${local.name_prefix} redis"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 1
  automatic_failover_enabled = false
  engine                     = "redis"
  engine_version             = "7.0"
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.main[0].name
  security_group_ids         = [aws_security_group.redis.id]
}
