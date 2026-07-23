variable "bucket_name" {
  type = string
}

variable "domain_name" {
  description = "Frontend domain (e.g. example.com or www.example.com). Empty = *.cloudfront.net only."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
