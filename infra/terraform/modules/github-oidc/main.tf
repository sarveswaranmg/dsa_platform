# GitHub Actions authenticates via OIDC (short-lived, per-run tokens) —
# never long-lived AWS access keys, matching this project's posture
# elsewhere (RS256 asymmetric keys, SES via instance/task role, etc.).

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # SHA1 thumbprint of the root CA in token.actions.githubusercontent.com's
  # current TLS chain (verified live via openssl s_client, not copied from
  # memory — GitHub has changed CAs before and a stale value here is a
  # classic footgun). AWS no longer actually validates this for
  # well-known public CAs, but the field is still required. Re-verify with:
  #   openssl s_client -connect token.actions.githubusercontent.com:443 \
  #     -servername token.actions.githubusercontent.com -showcerts </dev/null \
  #     | openssl x509 -noout -fingerprint -sha1
  thumbprint_list = ["ab9d0263244dd0326eb60715705a667e79cfe998"]
  tags            = var.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:ref:${var.allowed_ref}"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "github-actions-deploy"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = var.ecr_repository_arns
  }

  statement {
    sid       = "EcsDescribe"
    actions   = ["ecs:DescribeServices", "ecs:DescribeTasks", "ecs:DescribeTaskDefinition", "ecs:ListTasks"]
    resources = ["*"]
  }

  statement {
    sid       = "EcsRunMigrateTask"
    actions   = ["ecs:RunTask"]
    resources = var.ecs_task_definition_arns
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [var.ecs_cluster_arn]
    }
  }

  statement {
    sid       = "EcsUpdateServices"
    actions   = ["ecs:UpdateService"]
    resources = var.ecs_service_arns
  }

  statement {
    sid       = "EcsRegisterTaskDefinition"
    actions   = ["ecs:RegisterTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = var.passable_role_arns
  }

  statement {
    sid       = "SyncFrontend"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [var.frontend_bucket_arn, "${var.frontend_bucket_arn}/*"]
  }

  statement {
    sid       = "InvalidateCdn"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [var.cloudfront_distribution_arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy-permissions"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.deploy.json
}
