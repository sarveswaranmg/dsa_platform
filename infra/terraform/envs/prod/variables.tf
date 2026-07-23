variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "dsa-platform"
}

variable "environment" {
  type    = string
  default = "prod"
}

# --- TLS / DNS (optional — see infra/terraform/README.md) ---

variable "domain_name" {
  description = "Frontend domain, e.g. \"example.com\". Empty = HTTP-only ALB + default *.cloudfront.net cert, no Route53/ACM resources created."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Required only when domain_name is set — the zone must already exist and be delegated."
  type        = string
  default     = ""
}

# --- GitHub OIDC (Prompt 8's deploy role) ---

variable "github_org" {
  type    = string
  default = ""
}

variable "github_repo" {
  type    = string
  default = "dsa_platform"
}

# --- SES ---

variable "ses_from_address" {
  description = "Must be a verified SES identity (or domain) — see services/exam/app/notifications/ses_sender.py."
  type        = string
  default     = "no-reply@example.com"
}

# --- Sizing (sane defaults; override in terraform.tfvars for real load) ---

variable "gateway_desired_count" {
  type    = number
  default = 2
}

variable "exam_desired_count" {
  type    = number
  default = 2
}

variable "question_desired_count" {
  type    = number
  default = 2
}

variable "judge_instance_type" {
  type    = string
  default = "t3.large"
}

variable "judge_min_size" {
  type    = number
  default = 1
}

variable "judge_max_size" {
  type    = number
  default = 10
}

variable "judge_desired_capacity" {
  type    = number
  default = 2
}

variable "judge_runtime" {
  description = "\"runc\" (default) or \"gvisor\" — see docs/DECISIONS.md."
  type        = string
  default     = "runc"
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

# --- Image tags (deploy.yml overwrites these via -var at deploy time;
#     the values here are only used for the very first `terraform apply`,
#     before any image has been pushed — see README) ---

variable "image_tag" {
  type    = string
  default = "initial"
}
