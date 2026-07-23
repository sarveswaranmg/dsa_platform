variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "domain_name" {
  description = "API domain (e.g. api.example.com). Empty string = HTTP-only, no ACM/Route53 (see infra/terraform/README.md)."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Required only when domain_name is set."
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
