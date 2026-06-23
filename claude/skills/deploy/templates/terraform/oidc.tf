###############################################################################
# oidc.tf — GitHub Actions OIDC trust + role.
#
# Lets GitHub Actions assume an AWS role without long-lived access keys.
# The role is allowed to:
#   * push images to this project's ECR repo
#   * create/update this project's ECS Express Mode service (the deploy action
#     uses ecs:*ExpressGatewayService + RegisterTaskDefinition + UpdateService)
#   * pass the execution + infrastructure roles to ECS
#
# Trust is scoped to the configured org/repo and the configured branch.
###############################################################################

# The GitHub OIDC provider is account-wide and already exists in this account
# (only one per URL is allowed). Reference it instead of creating a second.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_actions_trust" {
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

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_owner}/${var.github_repo}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "github-actions-${var.project_name}"
  description        = "Assumed by GitHub Actions via OIDC to push images and deploy the ECS Express service"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json

  tags = {
    Name = "github-actions-${var.project_name}"
  }
}

data "aws_iam_policy_document" "github_actions_inline" {
  # ECR auth token is account-wide, not resource-scoped.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Push/pull to this project's repo only.
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
    resources = [aws_ecr_repository.app.arn]
  }

  # Deploy the ECS Express service. These ECS actions don't support
  # resource-level scoping for create/list, so they target "*"; the OIDC trust
  # policy already scopes WHO can assume the role to this repo+branch.
  statement {
    sid    = "EcsExpressDeploy"
    effect = "Allow"
    actions = [
      "ecs:CreateCluster",
      "ecs:DescribeClusters",
      "ecs:CreateExpressGatewayService",
      "ecs:UpdateExpressGatewayService",
      "ecs:DescribeExpressGatewayService",
      "ecs:RegisterTaskDefinition",
      "ecs:DescribeServices",
      "ecs:ListServices",
      "ecs:UpdateService",
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeListeners",
    ]
    resources = ["*"]
  }

  # The deploy action passes the execution + infrastructure roles to ECS.
  statement {
    sid     = "PassEcsRoles"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.ecs_execution.arn,
      aws_iam_role.ecs_infrastructure.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "${var.project_name}-github-actions-inline"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_inline.json
}
