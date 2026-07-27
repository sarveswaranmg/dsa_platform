variable "github_org" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "allowed_ref" {
  description = "Restricts which branch/ref can assume this role — matches deploy.yml running only after ci.yml passes on main."
  type        = string
  default     = "refs/heads/main"
}

variable "ecr_repository_arns" {
  type = list(string)
}

variable "ecs_cluster_arn" {
  type = string
}

variable "ecs_service_arns" {
  type = list(string)
}

variable "migrate_task_definition_families" {
  description = "Task definition family names (e.g. \"exam-migrate\") — RunTask is scoped to a family-wildcard ARN pattern built from these, since deploy.yml registers a new revision every deploy."
  type        = list(string)
}

variable "passable_role_arns" {
  description = "Task + execution role ARNs deploy.yml needs to pass when registering new task definition revisions."
  type        = list(string)
}

variable "frontend_bucket_arn" {
  type = string
}

variable "cloudfront_distribution_arn" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
