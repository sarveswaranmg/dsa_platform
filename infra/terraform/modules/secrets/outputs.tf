output "rs256_private_key_secret_arn" {
  value = aws_secretsmanager_secret.rs256_private_key.arn
}

output "rs256_public_key_secret_arn" {
  value = aws_secretsmanager_secret.rs256_public_key.arn
}

output "google_client_id_secret_arn" {
  value = aws_secretsmanager_secret.google_client_id.arn
}

output "google_client_secret_secret_arn" {
  value = aws_secretsmanager_secret.google_client_secret.arn
}

output "google_redirect_uri_secret_arn" {
  value = aws_secretsmanager_secret.google_redirect_uri.arn
}
