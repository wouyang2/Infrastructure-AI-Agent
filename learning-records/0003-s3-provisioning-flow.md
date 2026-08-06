# Learning Record 0003: S3 Provisioning Flow

## Date
2026-08-06

## Topic
Moving from S3/IAM concepts to a real project provisioning workflow.

## What changed
The project now has a concrete AWS S3 provisioning path:

- authenticate locally with AWS credentials or profile
- dry-run the provisioning script
- create the S3 bucket, public access block, encryption, tags, IAM policy, and optional ECS role
- configure the app with S3 media environment variables
- verify behavior with a smoke upload

## Key insight
S3 app configuration and AWS permission are separate. Bucket environment variables tell the application where to store media, while AWS credentials and IAM policies decide whether AWS allows the operation.

## Project connection
This supports the production direction of moving uploaded inspection images/videos out of local container storage and into object storage, while keeping access private through IAM and presigned URLs.

## Next useful lesson
AWS deployment shape for this project: how API, worker, Redis, PostgreSQL, S3, and secrets fit together in a cloud environment.
