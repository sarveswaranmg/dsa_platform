variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security groups (ECS services, migrate tasks) allowed to reach Postgres on 5432."
  type        = list(string)
  default     = []
}

variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "allocated_storage" {
  description = "Storage in GB."
  type        = number
  default     = 50
}

variable "multi_az" {
  type    = bool
  default = true
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  description = "Only set true for throwaway/test environments — never in real prod."
  type        = bool
  default     = false
}

variable "databases" {
  description = "Logical databases + owning roles to create on this instance."
  type        = list(string)
  default     = ["exam", "question"]
}

variable "tags" {
  type    = map(string)
  default = {}
}
