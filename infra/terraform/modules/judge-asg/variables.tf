variable "name" {
  type    = string
  default = "judge"
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecr_repository_url" {
  description = "judge's own ECR repo (the worker image, not the sandbox runner images)."
  type        = string
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "judge_runtime" {
  description = "\"runc\" (default) or \"gvisor\" — installs and registers gVisor on the AMI when set. See docs/DECISIONS.md."
  type        = string
  default     = "runc"
}

variable "instance_type" {
  type    = string
  default = "t3.large"
}

variable "min_size" {
  type    = number
  default = 1
}

variable "max_size" {
  type    = number
  default = 10
}

variable "desired_capacity" {
  type    = number
  default = 2
}

variable "submissions_queue_name" {
  type = string
}

variable "submissions_queue_arn" {
  type = string
}

variable "verdicts_queue_arn" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "environment" {
  description = "Plain (non-secret) env vars for the judge container (SQS/S3 endpoint URLs, queue names, JUDGE_RUNTIME, etc.)."
  type        = map(string)
  default     = {}
}

variable "scale_up_threshold" {
  description = "Visible messages above which the ASG scales out."
  type        = number
  default     = 20
}

variable "scale_down_threshold" {
  description = "Visible messages below which the ASG scales in."
  type        = number
  default     = 2
}

variable "tags" {
  type    = map(string)
  default = {}
}
