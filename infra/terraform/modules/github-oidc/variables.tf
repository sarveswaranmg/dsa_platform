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

variable "ecs_task_definition_arns" {
  description = "Includes both the long-running services and the migrate tasks — RegisterTaskDefinition is scoped by family, not by ARN, but PassRole below needs the concrete role ARNs."
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
