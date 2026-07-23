variable "name" {
  description = "Name prefix for secret names."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
