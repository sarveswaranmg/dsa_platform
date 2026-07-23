output "address" {
  value = aws_db_instance.this.address
}

output "port" {
  value = aws_db_instance.this.port
}

output "security_group_id" {
  value = aws_security_group.this.id
}

output "database_url_secret_arns" {
  description = "Map of database name -> Secrets Manager ARN holding its full DATABASE_URL."
  value       = { for db in var.databases : db => aws_secretsmanager_secret.database_url[db].arn }
}
