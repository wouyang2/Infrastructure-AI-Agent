from __future__ import annotations

from scripts.aws.provision_s3_media import ProvisionPlan, media_policy_document


def test_media_policy_document_limits_access_to_bucket_prefix() -> None:
    plan = ProvisionPlan(
        region="us-east-1",
        account_id="123456789012",
        bucket_name="infra-agent-media-123456789012-us-east-1",
        prefix="inspection-media",
        policy_name="InfraAgentMediaS3Access",
        role_name="InfraAgentMediaEcsTaskRole",
    )

    policy = media_policy_document(plan)

    assert policy["Version"] == "2012-10-17"
    object_statement = policy["Statement"][0]
    assert object_statement["Action"] == [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
    ]
    assert (
        object_statement["Resource"]
        == "arn:aws:s3:::infra-agent-media-123456789012-us-east-1/inspection-media/*"
    )
    assert object_statement["Resource"] != "*"

    list_statement = policy["Statement"][1]
    assert list_statement["Action"] == "s3:ListBucket"
    assert list_statement["Resource"] == "arn:aws:s3:::infra-agent-media-123456789012-us-east-1"
    assert list_statement["Condition"] == {
        "StringLike": {"s3:prefix": "inspection-media/*"}
    }
