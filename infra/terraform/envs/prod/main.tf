# =============================================================================
# Foundation: network, ECR, secrets
# =============================================================================

module "vpc" {
  source = "../../modules/vpc"
  name   = local.name
  tags   = local.tags
}

module "ecr" {
  source = "../../modules/ecr"
  tags   = local.tags
}

module "secrets" {
  source = "../../modules/secrets"
  name   = local.name
  tags   = local.tags
}

# =============================================================================
# Data stores
# =============================================================================

module "rds" {
  source             = "../../modules/rds"
  name               = local.name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  instance_class     = var.rds_instance_class
  databases          = ["exam", "question"]
  allowed_security_group_ids = [
    module.ecs_service_exam.security_group_id,
    module.ecs_service_question.security_group_id,
    module.ecs_migrate_exam.security_group_id,
    module.ecs_migrate_question.security_group_id,
  ]
  tags = local.tags
}

module "elasticache" {
  source             = "../../modules/elasticache"
  name               = local.name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  node_type          = var.redis_node_type
  allowed_security_group_ids = [
    module.ecs_service_gateway.security_group_id,
    module.ecs_service_exam.security_group_id,
  ]
  tags = local.tags
}

module "sqs" {
  source = "../../modules/sqs"
  name   = local.name
  tags   = local.tags
}

module "s3_app" {
  source               = "../../modules/s3-app"
  bucket_name          = "${local.name}-submissions"
  cors_allowed_origins = [local.frontend_origin]
  tags                 = local.tags
}

# =============================================================================
# Edge: ALB, ECS cluster, frontend CDN
# =============================================================================

module "alb" {
  source            = "../../modules/alb"
  name              = local.name
  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnet_ids
  domain_name       = local.api_domain
  route53_zone_id   = var.route53_zone_id
  tags              = local.tags
}

module "ecs_cluster" {
  source = "../../modules/ecs-cluster"
  name   = local.name
  vpc_id = module.vpc.vpc_id
  tags   = local.tags
}

module "frontend_cdn" {
  source = "../../modules/frontend-cdn"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
  bucket_name     = "${local.name}-frontend"
  domain_name     = var.domain_name
  route53_zone_id = var.route53_zone_id
  tags            = local.tags
}

# =============================================================================
# ECS services — gateway (public, via ALB), exam + question (Cloud Map only)
# =============================================================================

data "aws_iam_policy_document" "gateway_task" {
  # Gateway proxies and rate-limits; it holds no AWS-resource permissions of
  # its own beyond what the execution role already grants (secrets read).
  statement {
    sid       = "Noop"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

module "ecs_service_gateway" {
  source                 = "../../modules/ecs-service"
  name                   = "gateway"
  cluster_id             = module.ecs_cluster.cluster_id
  cluster_name           = module.ecs_cluster.cluster_name
  cloud_map_namespace_id = module.ecs_cluster.cloud_map_namespace_id
  vpc_id                 = module.vpc.vpc_id
  private_subnet_ids     = module.vpc.private_subnet_ids
  image                  = "${module.ecr.repository_urls["gateway"]}:${var.image_tag}"
  container_port         = 8000
  desired_count          = var.gateway_desired_count
  health_check_path      = "/healthz"
  task_role_policy_json  = data.aws_iam_policy_document.gateway_task.json

  environment = {
    EXAM_SERVICE_URL     = "http://exam.${local.cloud_map_dns}:8000"
    QUESTION_SERVICE_URL = "http://question.${local.cloud_map_dns}:8000"
    REDIS_URL            = "redis://${module.elasticache.primary_endpoint}:6379/0"
    CORS_ORIGINS         = jsonencode([local.frontend_origin])
  }

  secrets = {
    RS256_PUBLIC_KEY = module.secrets.rs256_public_key_secret_arn
  }

  alb = {
    listener_arn      = module.alb.primary_listener_arn
    security_group_id = module.alb.security_group_id
    path_patterns     = ["/*"]
    priority          = 100
  }

  tags = local.tags
}

data "aws_iam_policy_document" "exam_task" {
  statement {
    sid       = "SubmitJobs"
    actions   = ["sqs:SendMessage"]
    resources = [module.sqs.submissions_queue_arn]
  }
  statement {
    sid       = "ConsumeVerdicts"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
    resources = [module.sqs.verdicts_queue_arn]
  }
  statement {
    sid       = "SendEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }
}

module "ecs_service_exam" {
  source                     = "../../modules/ecs-service"
  name                       = "exam"
  cluster_id                 = module.ecs_cluster.cluster_id
  cluster_name               = module.ecs_cluster.cluster_name
  cloud_map_namespace_id     = module.ecs_cluster.cloud_map_namespace_id
  vpc_id                     = module.vpc.vpc_id
  private_subnet_ids         = module.vpc.private_subnet_ids
  image                      = "${module.ecr.repository_urls["exam"]}:${var.image_tag}"
  container_port             = 8000
  desired_count              = var.exam_desired_count
  health_check_path          = "/healthz"
  task_role_policy_json      = data.aws_iam_policy_document.exam_task.json
  allowed_security_group_ids = [module.ecs_service_gateway.security_group_id]

  environment = {
    REDIS_URL            = "redis://${module.elasticache.primary_endpoint}:6379/0"
    QUESTION_SERVICE_URL = "http://question.${local.cloud_map_dns}:8000"
    FRONTEND_BASE_URL    = local.frontend_origin
    SQS_ENDPOINT_URL     = local.sqs_endpoint_url
    SUBMISSIONS_QUEUE    = module.sqs.submissions_queue_name
    VERDICTS_QUEUE       = module.sqs.verdicts_queue_name
    EMAIL_BACKEND        = "ses"
    SES_FROM_ADDRESS     = var.ses_from_address
    ENV                  = "production"
  }

  secrets = {
    DATABASE_URL         = module.rds.database_url_secret_arns["exam"]
    RS256_PRIVATE_KEY    = module.secrets.rs256_private_key_secret_arn
    GOOGLE_CLIENT_ID     = module.secrets.google_client_id_secret_arn
    GOOGLE_CLIENT_SECRET = module.secrets.google_client_secret_secret_arn
    GOOGLE_REDIRECT_URI  = module.secrets.google_redirect_uri_secret_arn
  }

  tags = local.tags
}

data "aws_iam_policy_document" "question_task" {
  statement {
    sid       = "TestCaseFiles"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${module.s3_app.bucket_arn}/*"]
  }
}

module "ecs_service_question" {
  source                     = "../../modules/ecs-service"
  name                       = "question"
  cluster_id                 = module.ecs_cluster.cluster_id
  cluster_name               = module.ecs_cluster.cluster_name
  cloud_map_namespace_id     = module.ecs_cluster.cloud_map_namespace_id
  vpc_id                     = module.vpc.vpc_id
  private_subnet_ids         = module.vpc.private_subnet_ids
  image                      = "${module.ecr.repository_urls["question"]}:${var.image_tag}"
  container_port             = 8000
  desired_count              = var.question_desired_count
  health_check_path          = "/healthz"
  task_role_policy_json      = data.aws_iam_policy_document.question_task.json
  allowed_security_group_ids = [module.ecs_service_gateway.security_group_id]

  environment = {
    S3_ENDPOINT_URL         = local.s3_endpoint_url
    S3_PRESIGN_ENDPOINT_URL = local.s3_endpoint_url
    S3_BUCKET               = module.s3_app.bucket_name
    ENV                     = "production"
  }

  secrets = {
    DATABASE_URL     = module.rds.database_url_secret_arns["question"]
    RS256_PUBLIC_KEY = module.secrets.rs256_public_key_secret_arn
  }

  tags = local.tags
}

# =============================================================================
# One-off migrate tasks (exam-migrate, question-migrate) — same images as
# their services, invoked by deploy.yml via `aws ecs run-task`.
# =============================================================================

module "ecs_migrate_exam" {
  source = "../../modules/ecs-migrate-task"
  name   = "exam-migrate"
  image  = "${module.ecr.repository_urls["exam"]}:${var.image_tag}"
  vpc_id = module.vpc.vpc_id

  environment = {
    ENV = "production"
  }

  secrets = {
    DATABASE_URL      = module.rds.database_url_secret_arns["exam"]
    RS256_PRIVATE_KEY = module.secrets.rs256_private_key_secret_arn
  }

  tags = local.tags
}

module "ecs_migrate_question" {
  source = "../../modules/ecs-migrate-task"
  name   = "question-migrate"
  image  = "${module.ecr.repository_urls["question"]}:${var.image_tag}"
  vpc_id = module.vpc.vpc_id

  environment = {
    ENV = "production"
  }

  secrets = {
    DATABASE_URL     = module.rds.database_url_secret_arns["question"]
    RS256_PUBLIC_KEY = module.secrets.rs256_public_key_secret_arn
  }

  tags = local.tags
}

# =============================================================================
# Judge — dedicated EC2 ASG
# =============================================================================

module "judge_asg" {
  source                 = "../../modules/judge-asg"
  vpc_id                 = module.vpc.vpc_id
  private_subnet_ids     = module.vpc.private_subnet_ids
  ecr_repository_url     = module.ecr.repository_urls["judge"]
  image_tag              = var.image_tag
  judge_runtime          = var.judge_runtime
  instance_type          = var.judge_instance_type
  min_size               = var.judge_min_size
  max_size               = var.judge_max_size
  desired_capacity       = var.judge_desired_capacity
  submissions_queue_name = module.sqs.submissions_queue_name
  submissions_queue_arn  = module.sqs.submissions_queue_arn
  verdicts_queue_arn     = module.sqs.verdicts_queue_arn
  s3_bucket_arn          = module.s3_app.bucket_arn

  environment = {
    SQS_ENDPOINT_URL  = local.sqs_endpoint_url
    S3_ENDPOINT_URL   = local.s3_endpoint_url
    SUBMISSIONS_QUEUE = module.sqs.submissions_queue_name
    VERDICTS_QUEUE    = module.sqs.verdicts_queue_name
    S3_BUCKET         = module.s3_app.bucket_name
    SCRATCH_ROOT      = "/tmp/dsa-judge"
  }

  tags = local.tags
}

# =============================================================================
# GitHub Actions OIDC deploy role (Prompt 8's deploy.yml assumes this)
# =============================================================================

module "github_oidc" {
  source      = "../../modules/github-oidc"
  github_org  = var.github_org
  github_repo = var.github_repo

  ecr_repository_arns = values(module.ecr.repository_arns)
  ecs_cluster_arn     = module.ecs_cluster.cluster_id
  ecs_service_arns = [
    module.ecs_service_gateway.service_arn,
    module.ecs_service_exam.service_arn,
    module.ecs_service_question.service_arn,
  ]
  ecs_task_definition_arns = [
    module.ecs_migrate_exam.task_definition_arn,
    module.ecs_migrate_question.task_definition_arn,
  ]
  passable_role_arns = [
    module.ecs_service_gateway.task_role_arn,
    module.ecs_service_gateway.execution_role_arn,
    module.ecs_service_exam.task_role_arn,
    module.ecs_service_exam.execution_role_arn,
    module.ecs_service_question.task_role_arn,
    module.ecs_service_question.execution_role_arn,
    module.ecs_migrate_exam.task_role_arn,
    module.ecs_migrate_exam.execution_role_arn,
    module.ecs_migrate_question.task_role_arn,
    module.ecs_migrate_question.execution_role_arn,
  ]
  frontend_bucket_arn         = module.frontend_cdn.bucket_arn
  cloudfront_distribution_arn = module.frontend_cdn.distribution_arn

  tags = local.tags
}
