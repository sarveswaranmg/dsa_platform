locals {
  name = "${var.project}-${var.environment}"

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  frontend_origin = var.domain_name != "" ? "https://${var.domain_name}" : "https://${module.frontend_cdn.distribution_domain_name}"
  api_domain      = var.domain_name != "" ? "api.${var.domain_name}" : ""

  sqs_endpoint_url = "https://sqs.${var.aws_region}.amazonaws.com"
  s3_endpoint_url  = "https://s3.${var.aws_region}.amazonaws.com"

  cloud_map_dns = module.ecs_cluster.cloud_map_namespace_name
}
