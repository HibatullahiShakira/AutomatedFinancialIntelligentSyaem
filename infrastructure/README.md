# Terraform configuration

This folder contains the Phase 0 IaC baseline for AMSS:

- VPC with public/private subnets across two AZs
- Internet gateway + NAT gateway + route tables
- Security groups for app, Postgres, and Redis
- S3 buckets (event store, ML artifacts, documents)
- SQS FIFO queue + DLQ
- ECR repositories
- Secrets Manager secret scaffold
- Optional stateful resources (RDS Postgres + ElastiCache Redis)

## Usage

1. Copy `terraform.tfvars.example` to `terraform.tfvars`.
2. Provide a secure `db_password`.
3. Keep `enable_stateful_resources = false` for low-cost validation runs.
4. Run:

```bash
terraform init
terraform fmt -recursive
terraform validate
terraform plan
```
