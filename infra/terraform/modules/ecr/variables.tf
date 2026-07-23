variable "repository_names" {
  description = "One ECR repo per backend service."
  type        = list(string)
  default     = ["gateway", "exam", "question", "judge"]
}

variable "image_tag_mutability" {
  type    = string
  default = "IMMUTABLE"
}

variable "untagged_image_expiry_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}
