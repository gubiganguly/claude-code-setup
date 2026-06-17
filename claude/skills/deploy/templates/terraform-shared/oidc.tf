###############################################################################
# oidc.tf — GitHub Actions OIDC trust + role.
#
# Lets GitHub Actions assume an AWS role without long-lived access keys.
# The role is allowed to:
#   * push images to this project's ECR repo
#   * trigger App Runner deployments on this project's service
#
# Trust is scoped to the configured org/repo and the configured branch.
###############################################################################

# The GitHub OIDC provider is account-wide and already exists in this account
# (the LBMC stack created it — only one per URL is allowed). Reference the
# existing one instead of creating a second.
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
  description        = "Assumed by GitHub Actions via OIDC to push images and trigger deploys"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json

  tags = {
    Name = "github-actions-${var.project_name}"
  }
}

data "aws_iam_policy_document" "github_actions_inline" {
  # ECR auth token is account-wide, not resource-scoped
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Push/pull to this project's repo only
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

  # Resolve the service ARN. ListServices is a list operation that does not
  # support resource-level scoping, so it must target "*".
  statement {
    sid       = "AppRunnerList"
    effect    = "Allow"
    actions   = ["apprunner:ListServices"]
    resources = ["*"]
  }

  # Kick App Runner deploys and poll for RUNNING (scoped to this service).
  # auto-deploy is on, but this also lets CI force-roll and wait on status.
  statement {
    sid    = "AppRunnerDeploy"
    effect = "Allow"
    actions = [
      "apprunner:StartDeployment",
      "apprunner:DescribeService",
    ]
    resources = [aws_apprunner_service.app.arn]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "${var.project_name}-github-actions-inline"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_inline.json
}
