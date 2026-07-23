variable "name" {
  type = string
}

variable "visibility_timeout_seconds" {
  description = "Must exceed the judge worker's worst-case processing time for a submission."
  type        = number
  default     = 120
}

variable "max_receive_count" {
  description = "Redeliveries before a message moves to the DLQ."
  type        = number
  default     = 5
}

variable "tags" {
  type    = map(string)
  default = {}
}
