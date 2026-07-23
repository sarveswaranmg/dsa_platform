variable "name" {
  description = "e.g. exam-migrate, question-migrate."
  type        = string
}

variable "image" {
  description = "Same image as the service's ecs-service module call — migrate.sh is baked into the app image (see services/exam/Dockerfile, services/question/Dockerfile)."
  type        = string
}

variable "vpc_id" {
  description = "Needed for this task's own security group (RDS grants ingress from it) — the task definition itself has no network_configuration; deploy.yml supplies subnets/SGs at `aws ecs run-task` time."
  type        = string
}

variable "environment" {
  type    = map(string)
  default = {}
}

variable "secrets" {
  type    = map(string)
  default = {}
}

variable "task_role_policy_json" {
  description = "Almost always just Secrets Manager read for the DB URL — same shape as ecs-service."
  type        = string
  default     = null
}

variable "cpu" {
  type    = number
  default = 256
}

variable "memory" {
  type    = number
  default = 512
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}
