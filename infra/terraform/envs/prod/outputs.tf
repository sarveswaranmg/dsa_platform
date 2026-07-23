output "alb_dns_name" {
  value = module.alb.alb_dns_name
}

output "api_domain" {
  value = local.api_domain
}

output "frontend_domain" {
  value = local.frontend_origin
}

output "cloudfront_distribution_id" {
  value = module.frontend_cdn.distribution_id
}

output "cloudfront_distribution_domain_name" {
  value = module.frontend_cdn.distribution_domain_name
}

output "frontend_bucket_name" {
  value = module.frontend_cdn.bucket_name
}

output "rds_address" {
  value = module.rds.address
}

output "redis_endpoint" {
  value = module.elasticache.primary_endpoint
}

output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}

output "ecs_cluster_name" {
  value = module.ecs_cluster.cluster_name
}

output "submissions_queue_url" {
  value = module.sqs.submissions_queue_url
}

output "judge_asg_name" {
  value = module.judge_asg.asg_name
}

output "github_actions_role_arn" {
  description = "Set this as the AWS_ROLE_ARN GitHub secret."
  value       = module.github_oidc.role_arn
}

output "secrets_needing_manual_population" {
  description = "Secrets Manager ARNs Terraform created as shells — populate real values post-apply (see README)."
  value = {
    google_client_id     = module.secrets.google_client_id_secret_arn
    google_client_secret = module.secrets.google_client_secret_secret_arn
    google_redirect_uri  = module.secrets.google_redirect_uri_secret_arn
  }
}
