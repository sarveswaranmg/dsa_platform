variable "name" {
  description = "Service name (gateway, exam, question)."
  type        = string
}

variable "cluster_id" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "cloud_map_namespace_id" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "image" {
  description = "Full ECR image URI:tag."
  type        = string
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 2
}

variable "environment" {
  description = "Plain (non-secret) env vars."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Env var name -> Secrets Manager ARN, injected via the ECS secrets mechanism."
  type        = map(string)
  default     = {}
}

variable "task_role_policy_json" {
  description = "Extra least-privilege IAM policy JSON for this service's task role (SQS/S3/SES/etc. — whatever this specific service needs). Null = no extra policy."
  type        = string
  default     = null
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to reach this service on container_port (e.g. gateway's SG, for exam/question)."
  type        = list(string)
  default     = []
}

variable "health_check_path" {
  type    = string
  default = "/healthz"
}

variable "alb" {
  description = "Set only for the service that's publicly reachable (gateway). Null = Cloud Map only, no ALB target group."
  type = object({
    listener_arn      = string
    security_group_id = string
    path_patterns     = list(string)
    priority          = number
  })
  default = null
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
