from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, cast

import boto3
from botocore.exceptions import ClientError

from test_terraform_config import TEST_AWS_REGION

ResourceChecker = Callable[[Any, str], bool]


def _check_lambda(client: Any, name: str) -> bool:
    try:
        client.get_function(FunctionName=name)
        return True
    except client.exceptions.ResourceNotFoundException:
        return False


def _check_iam_role(client: Any, name: str) -> bool:
    try:
        client.get_role(RoleName=name)
        return True
    except client.exceptions.NoSuchEntityException:
        return False


def _check_log_group(client: Any, name: str) -> bool:
    response = client.describe_log_groups(logGroupNamePrefix=name, limit=1)
    for group in response.get("logGroups", []):
        if group.get("logGroupName") == name:
            return True
    return False


def _check_dynamodb_table(client: Any, name: str) -> bool:
    try:
        client.describe_table(TableName=name)
        return True
    except client.exceptions.ResourceNotFoundException:
        return False


def _check_s3_bucket(client: Any, name: str) -> bool:
    try:
        client.head_bucket(Bucket=name)
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "404":
            return False
        raise


def _check_sqs_queue(client: Any, name: str) -> bool:
    try:
        client.get_queue_url(QueueName=name)
        return True
    except client.exceptions.QueueDoesNotExist:
        return False


def _check_sns_topic(client: Any, arn: str) -> bool:
    try:
        client.get_topic_attributes(TopicArn=arn)
        return True
    except client.exceptions.NotFoundException:
        return False


def _check_ssm_parameter(client: Any, name: str) -> bool:
    try:
        client.get_parameter(Name=name)
        return True
    except client.exceptions.ParameterNotFound:
        return False


def _check_eventbridge_rule(client: Any, name: str) -> bool:
    try:
        client.describe_rule(Name=name)
        return True
    except client.exceptions.ResourceNotFoundException:
        return False


def _check_api_gateway_rest_api(client: Any, api_id: str) -> bool:
    try:
        client.get_rest_api(restApiId=api_id)
        return True
    except client.exceptions.NotFoundException:
        return False


RESOURCE_CHECKERS: dict[str, ResourceChecker] = {
    "aws_s3_bucket": _check_s3_bucket,
    "aws_lambda_function": _check_lambda,
    "aws_iam_role": _check_iam_role,
    "aws_cloudwatch_log_group": _check_log_group,
    "aws_dynamodb_table": _check_dynamodb_table,
    "aws_sqs_queue": _check_sqs_queue,
    "aws_sns_topic": _check_sns_topic,
    "aws_cloudwatch_event_rule": _check_eventbridge_rule,
    "aws_api_gateway_rest_api": _check_api_gateway_rest_api,
    "aws_ssm_parameter": _check_ssm_parameter,
}

RESOURCE_TO_CLIENT: dict[str, str] = {
    "aws_s3_bucket": "s3",
    "aws_lambda_function": "lambda",
    "aws_iam_role": "iam",
    "aws_cloudwatch_log_group": "logs",
    "aws_dynamodb_table": "dynamodb",
    "aws_sqs_queue": "sqs",
    "aws_sns_topic": "sns",
    "aws_cloudwatch_event_rule": "events",
    "aws_api_gateway_rest_api": "apigateway",
    "aws_ssm_parameter": "ssm",
}

_NAME_FIELDS: dict[str, str] = {
    "aws_s3_bucket": "bucket",
    "aws_lambda_function": "function_name",
    "aws_iam_role": "name",
    "aws_cloudwatch_log_group": "name",
    "aws_dynamodb_table": "name",
    "aws_sqs_queue": "name",
    "aws_sns_topic": "arn",
    "aws_cloudwatch_event_rule": "name",
    "aws_api_gateway_rest_api": "id",
    "aws_ssm_parameter": "name",
}


def check_resource_exists(
    resource_type: str,
    resource_name: str,
    region: str = TEST_AWS_REGION,
) -> bool:
    if resource_type not in RESOURCE_CHECKERS:
        supported = ", ".join(RESOURCE_CHECKERS)
        raise ValueError(
            f"Unsupported resource type: {resource_type}. Supported types: {supported}"
        )
    client = cast(Any, boto3).client(RESOURCE_TO_CLIENT[resource_type], region_name=region)
    return RESOURCE_CHECKERS[resource_type](client, resource_name)


def get_planned_creates(
    stack_dir: Path,
    timeout: int = 120,
) -> list[dict[str, object]]:
    result = subprocess.run(
        ["tofu", "plan", "-json", "-input=false"],
        capture_output=True,
        text=True,
        cwd=stack_dir,
        timeout=timeout,
        check=False,
    )
    creates: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "planned_change":
            continue
        change = entry.get("change", {})
        if change.get("action") != "create":
            continue
        resource = change.get("resource", {})
        resource_type = resource.get("resource_type", "")
        if resource_type not in RESOURCE_CHECKERS:
            continue
        after_values = change.get("change", {}).get("after", {})
        name_field = _NAME_FIELDS.get(resource_type, "name")
        resource_name = after_values.get(name_field, "")
        if resource_name:
            creates.append(
                {
                    "type": resource_type,
                    "name": resource_name,
                    "address": resource.get("addr", ""),
                    "values": after_values,
                }
            )
    return creates


def get_state_resources(stack_dir: Path) -> list[str]:
    result = subprocess.run(
        ["tofu", "state", "list"],
        capture_output=True,
        text=True,
        cwd=stack_dir,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def find_orphaned_resources(
    stack_dir: Path,
    region: str = TEST_AWS_REGION,
) -> list[dict[str, str]]:
    orphaned: list[dict[str, str]] = []
    for resource in get_planned_creates(stack_dir):
        resource_type = str(resource["type"])
        resource_name = str(resource["name"])
        address = str(resource["address"])
        if check_resource_exists(resource_type, resource_name, region):
            orphaned.append(
                {
                    "type": resource_type,
                    "name": resource_name,
                    "address": address,
                    "import_command": f"tofu import {address} {resource_name}",
                }
            )
    return orphaned
