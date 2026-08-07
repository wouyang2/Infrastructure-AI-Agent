# AWS Resources

## Knowledge

- [AWS Overview: What is cloud computing?](https://docs.aws.amazon.com/whitepapers/latest/aws-overview/what-is-cloud-computing.html)
  Official AWS overview of cloud computing. Use for: explaining what cloud providers replace compared with local servers and local disks.

- [Overview of Amazon Web Services](https://docs.aws.amazon.com/whitepapers/latest/aws-overview/introduction.html)
  Official AWS whitepaper describing AWS service categories and the pay-as-you-go model. Use for: mapping application needs to AWS service families.

- [Amazon S3 product overview](https://aws.amazon.com/s3/)
  Official S3 overview. Use for: explaining object storage, media/file storage, scalability, and why uploaded images/videos should move out of app containers.

- [Amazon S3 objects overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingObjects.html)
  Official S3 object model docs. Use for: bucket/key/object language and how files are addressed in S3.

- [S3 presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
  Official guide for temporary upload/download URLs. Use for: safe browser preview/download without public buckets.

- [What is IAM?](https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html)
  Official IAM introduction. Use for: explaining authentication, authorization, identities, permissions, and least privilege.

- [Getting started with IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/getting-started.html)
  Official IAM getting-started guide. Use for: roles, users, permissions, and secure access patterns.

- [Amazon ECS task definitions](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html)
  Official ECS documentation for describing containerized services. Use for: mapping the FastAPI and RQ worker containers to AWS deployment units.

- [Amazon RDS for PostgreSQL common tasks](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.CommonTasks.html)
  Official RDS PostgreSQL guide. Use for: replacing the Docker PostgreSQL container with a managed production database.

- [What is Amazon ElastiCache?](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/WhatIs.html)
  Official ElastiCache overview. Use for: replacing the Docker Redis container with managed Redis/Valkey-compatible infrastructure.

- [What is AWS Secrets Manager?](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)
  Official Secrets Manager overview. Use for: moving API keys, database URLs, and provider credentials out of local `.env` files.

## Wisdom (Communities)

- [AWS re:Post](https://repost.aws/)
  Official AWS community Q&A. Use for: practical troubleshooting and real-world AWS service behavior.

- [AWS Builders Library](https://aws.amazon.com/builders-library/)
  Engineering articles from Amazon practitioners. Use for: production design judgment after the basic AWS service map is clear.
