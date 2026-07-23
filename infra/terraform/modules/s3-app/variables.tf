variable "bucket_name" {
  type = string
}

variable "cors_allowed_origins" {
  description = "Origins allowed to PUT/GET straight to S3 from the browser (the examiner console). Matches services/question's s3_cors_origins."
  type        = list(string)
}

variable "tags" {
  type    = map(string)
  default = {}
}
