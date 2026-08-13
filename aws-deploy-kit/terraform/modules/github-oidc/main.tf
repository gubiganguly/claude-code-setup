###############################################################################
# modules/github-oidc — the role GitHub Actions assumes to deploy this service.
#
# No static AWS keys anywhere. Trust is scoped by the OIDC subject claim to one
# repo and one ref, so a fork or another branch cannot assume it.
#
# The OIDC PROVIDER itself is account-wide and created by the bootstrap stack;
# this module only looks it up.
###############################################################################

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
  }
}

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scope to this repo and ref. Without this condition ANY GitHub repo in the
    # world could assume the role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_owner}/${var.github_repo}:ref:refs/heads/${var.github_branch}",
        "repo:${var.github_owner}/${var.github_repo}:environment:*",
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name                 = "${var.service_name}-github-actions"
  description          = "OIDC deploy role for ${var.github_owner}/${var.github_repo}"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600

  tags = { Name = "${var.service_name}-github-actions" }
}

data "aws_iam_policy_document" "inline" {
  # The auth-token call is account-wide by design; it grants nothing on its own.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [var.ecr_repository_arn]
  }

  # ECS Express create/describe/update do not support resource-level scoping,
  # so these are "*". The trust policy above is what constrains who can get
  # here in the first place.
  statement {
    sid    = "EcsExpressDeploy"
    effect = "Allow"
    actions = [
      "ecs:DescribeClusters",
      "ecs:CreateExpressGatewayService",
      "ecs:UpdateExpressGatewayService",
      "ecs:DescribeExpressGatewayService",
      "ecs:ListServices",
      "ecs:DescribeServices",
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeListeners",
    ]
    resources = ["*"]
  }

  # Handing roles to ECS is the classic privilege-escalation path, so it is
  # pinned to exactly the three roles this service uses.
  statement {
    sid     = "PassServiceRoles"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = compact([
      var.execution_role_arn,
      var.infrastructure_role_arn,
      var.task_role_arn,
    ])

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com", "ecs.amazonaws.com"]
    }
  }

  # Optional: let CI invalidate CloudFront after a deploy.
  dynamic "statement" {
    for_each = var.cloudfront_distribution_arn == null ? [] : [1]
    content {
      sid       = "CloudFrontInvalidate"
      effect    = "Allow"
      actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
      resources = [var.cloudfront_distribution_arn]
    }
  }
}

resource "aws_iam_role_policy" "inline" {
  name   = "${var.service_name}-github-actions-inline"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.inline.json
}
