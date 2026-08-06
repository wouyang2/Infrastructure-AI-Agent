from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any


PROJECT_TAGS = [
    {"Key": "Project", "Value": "Infrastructure-AI-Agent"},
    {"Key": "Component", "Value": "media-storage"},
    {"Key": "ManagedBy", "Value": "scripts/aws/provision_s3_media.py"},
]


@dataclass(frozen=True)
class ProvisionPlan:
    region: str
    account_id: str
    bucket_name: str
    prefix: str
    policy_name: str
    role_name: str | None

    @property
    def bucket_arn(self) -> str:
        return f"arn:aws:s3:::{self.bucket_name}"

    @property
    def object_arn(self) -> str:
        return f"{self.bucket_arn}/{self.prefix.rstrip('/')}/*"


def main() -> None:
    args = parse_args()
    boto3 = import_boto3()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    region = session.region_name or args.region
    sts = session.client("sts")
    try:
        identity = sts.get_caller_identity()
    except Exception as exc:
        if exc.__class__.__name__ == "NoCredentialsError":
            raise SystemExit(
                "Unable to locate AWS credentials.\n\n"
                "Use one of these options, then rerun the script:\n"
                "  1. Configure an AWS CLI/profile and pass --profile <name>\n"
                "  2. Export AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY\n"
                "  3. In deployed AWS compute, attach an IAM role to the service\n\n"
                "No S3 bucket or IAM policy was created."
            ) from exc
        raise
    account_id = identity["Account"]
    bucket_name = args.bucket or f"infra-agent-media-{account_id}-{region}"
    plan = ProvisionPlan(
        region=region,
        account_id=account_id,
        bucket_name=bucket_name,
        prefix=args.prefix,
        policy_name=args.policy_name,
        role_name=args.role_name if args.create_ecs_role else None,
    )

    print_plan(plan, identity, apply=args.apply)
    if not args.apply:
        return

    s3 = session.client("s3", region_name=region)
    iam = session.client("iam")
    ensure_bucket(s3, plan)
    ensure_bucket_security(s3, plan)
    policy_arn = ensure_policy(iam, plan)
    if plan.role_name:
        role_arn = ensure_ecs_task_role(iam, plan, policy_arn)
    else:
        role_arn = None

    print("\nProvisioned successfully.")
    print("\nAdd these to .env when you want the app to use S3:")
    print(f"MEDIA_STORAGE_BACKEND=s3")
    print(f"AWS_S3_MEDIA_BUCKET={plan.bucket_name}")
    print(f"AWS_REGION={plan.region}")
    print(f"AWS_S3_MEDIA_PREFIX={plan.prefix}")
    print("AWS_S3_PRESIGN_EXPIRES_SECONDS=900")
    if role_arn:
        print(f"\nECS task role ARN: {role_arn}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision S3 media storage resources for Infrastructure AI Agent."
    )
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--prefix", default="inspection-media")
    parser.add_argument("--policy-name", default="InfraAgentMediaS3Access")
    parser.add_argument("--role-name", default="InfraAgentMediaEcsTaskRole")
    parser.add_argument("--create-ecs-role", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually create/update AWS resources. Omit for dry-run.",
    )
    return parser.parse_args()


def import_boto3():
    try:
        import boto3
    except ImportError as exc:
        raise SystemExit(
            "boto3 is required. Install dependencies with: python3 -m pip install -r requirements.txt"
        ) from exc
    return boto3


def print_plan(plan: ProvisionPlan, identity: dict[str, Any], *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"Mode: {mode}")
    print(f"AWS caller ARN: {identity['Arn']}")
    print(f"AWS account: {plan.account_id}")
    print(f"Region: {plan.region}")
    print(f"Bucket: {plan.bucket_name}")
    print(f"Prefix: {plan.prefix}")
    print(f"Policy: {plan.policy_name}")
    if plan.role_name:
        print(f"ECS task role: {plan.role_name}")
    else:
        print("ECS task role: skipped")
    print("\nPolicy document:")
    print(json.dumps(media_policy_document(plan), indent=2))
    if not apply:
        print("\nDry run only. Re-run with --apply to create/update AWS resources.")


def ensure_bucket(s3, plan: ProvisionPlan) -> None:
    try:
        s3.head_bucket(Bucket=plan.bucket_name)
        print(f"Bucket already exists and is accessible: {plan.bucket_name}")
        return
    except Exception:
        pass

    create_kwargs: dict[str, Any] = {"Bucket": plan.bucket_name}
    if plan.region != "us-east-1":
        create_kwargs["CreateBucketConfiguration"] = {
            "LocationConstraint": plan.region,
        }
    s3.create_bucket(**create_kwargs)
    waiter = s3.get_waiter("bucket_exists")
    waiter.wait(Bucket=plan.bucket_name)
    print(f"Created bucket: {plan.bucket_name}")


def ensure_bucket_security(s3, plan: ProvisionPlan) -> None:
    s3.put_public_access_block(
        Bucket=plan.bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=plan.bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256",
                    },
                    "BucketKeyEnabled": True,
                }
            ]
        },
    )
    s3.put_bucket_tagging(Bucket=plan.bucket_name, Tagging={"TagSet": PROJECT_TAGS})
    print("Applied bucket public-access block, default encryption, and tags.")


def ensure_policy(iam, plan: ProvisionPlan) -> str:
    policy_doc = json.dumps(media_policy_document(plan))
    account_policy_arn = f"arn:aws:iam::{plan.account_id}:policy/{plan.policy_name}"
    try:
        iam.get_policy(PolicyArn=account_policy_arn)
        versions = iam.list_policy_versions(PolicyArn=account_policy_arn)["Versions"]
        non_default_versions = [
            version for version in versions if not version["IsDefaultVersion"]
        ]
        if len(versions) >= 5 and non_default_versions:
            oldest = sorted(non_default_versions, key=lambda item: item["CreateDate"])[0]
            iam.delete_policy_version(
                PolicyArn=account_policy_arn,
                VersionId=oldest["VersionId"],
            )
        iam.create_policy_version(
            PolicyArn=account_policy_arn,
            PolicyDocument=policy_doc,
            SetAsDefault=True,
        )
        print(f"Updated policy: {account_policy_arn}")
        return account_policy_arn
    except iam.exceptions.NoSuchEntityException:
        response = iam.create_policy(
            PolicyName=plan.policy_name,
            PolicyDocument=policy_doc,
            Description="Least-privilege S3 media access for Infrastructure AI Agent.",
            Tags=PROJECT_TAGS,
        )
        policy_arn = response["Policy"]["Arn"]
        print(f"Created policy: {policy_arn}")
        return policy_arn


def ensure_ecs_task_role(iam, plan: ProvisionPlan, policy_arn: str) -> str:
    trust_doc = json.dumps(ecs_task_trust_policy())
    try:
        response = iam.get_role(RoleName=plan.role_name)
        role_arn = response["Role"]["Arn"]
        iam.update_assume_role_policy(
            RoleName=plan.role_name,
            PolicyDocument=trust_doc,
        )
        print(f"Updated ECS task role trust policy: {role_arn}")
    except iam.exceptions.NoSuchEntityException:
        response = iam.create_role(
            RoleName=plan.role_name,
            AssumeRolePolicyDocument=trust_doc,
            Description="ECS task role for Infrastructure AI Agent media access.",
            Tags=PROJECT_TAGS,
        )
        role_arn = response["Role"]["Arn"]
        print(f"Created ECS task role: {role_arn}")

    attached = iam.list_attached_role_policies(RoleName=plan.role_name)[
        "AttachedPolicies"
    ]
    if not any(policy["PolicyArn"] == policy_arn for policy in attached):
        iam.attach_role_policy(RoleName=plan.role_name, PolicyArn=policy_arn)
        print(f"Attached policy to role: {policy_arn}")
    return role_arn


def media_policy_document(plan: ProvisionPlan) -> dict[str, Any]:
    prefix = plan.prefix.rstrip("/")
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "MediaObjectAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:DeleteObject",
                ],
                "Resource": plan.object_arn,
            },
            {
                "Sid": "MediaPrefixListAccess",
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": plan.bucket_arn,
                "Condition": {"StringLike": {"s3:prefix": f"{prefix}/*"}},
            },
        ],
    }


def ecs_task_trust_policy() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }


if __name__ == "__main__":
    main()
