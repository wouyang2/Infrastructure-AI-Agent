# Learning Record 0004: Production Request Lifecycle

## Date
2026-08-06

## Topic
Understanding how the Infrastructure AI Agent request flow changes in an AWS-style production deployment.

## What changed
The production mental model is now:

- S3 stores uploaded media bytes.
- PostgreSQL/RDS stores durable inspection records, prompts, notes, settings, media references, progress, and results.
- Redis/ElastiCache plus RQ coordinates queued work.
- The worker loads run metadata from PostgreSQL and media from S3.
- The API reads stored progress/results and sends them back to the UI.

## Key insight
Redis should coordinate work, PostgreSQL should preserve truth, and S3 should preserve files.

## Project connection
This helps guide future production upgrades such as reconciliation for stuck jobs, ECS worker/API deployment, S3-backed artifacts, and RDS-backed audit history.

## Next useful lesson
Secrets and runtime configuration: how AWS Secrets Manager, IAM roles, and environment variables replace local `.env` for deployed services.
