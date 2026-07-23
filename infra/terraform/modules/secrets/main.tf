# RS256 keypair: Terraform-generated (matches the dev keypair generation
# approach in infra/dev-keys/, just for real here) — exam is the only
# service that ever sees the private key; gateway/question get the public
# key only. Both end up in Terraform state, so the state backend (S3, see
# envs/prod/backend.tf) must have encryption at rest enabled.
resource "tls_private_key" "rs256" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_secretsmanager_secret" "rs256_private_key" {
  name = "${var.name}/rs256-private-key"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "rs256_private_key" {
  secret_id     = aws_secretsmanager_secret.rs256_private_key.id
  secret_string = tls_private_key.rs256.private_key_pem
}

resource "aws_secretsmanager_secret" "rs256_public_key" {
  name = "${var.name}/rs256-public-key"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "rs256_public_key" {
  secret_id     = aws_secretsmanager_secret.rs256_public_key.id
  secret_string = tls_private_key.rs256.public_key_pem
}

# Google OIDC client credentials: Terraform can't generate these — they come
# from a human creating an OAuth client in Google Cloud Console. These are
# shells with a placeholder value; populate the real ones post-apply (AWS
# CLI/console) and Terraform will never overwrite them again
# (lifecycle.ignore_changes on secret_string).
resource "aws_secretsmanager_secret" "google_client_id" {
  name = "${var.name}/google-client-id"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "google_client_id" {
  secret_id     = aws_secretsmanager_secret.google_client_id.id
  secret_string = "CHANGE-ME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "google_client_secret" {
  name = "${var.name}/google-client-secret"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "google_client_secret" {
  secret_id     = aws_secretsmanager_secret.google_client_secret.id
  secret_string = "CHANGE-ME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "google_redirect_uri" {
  name = "${var.name}/google-redirect-uri"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "google_redirect_uri" {
  secret_id     = aws_secretsmanager_secret.google_redirect_uri.id
  secret_string = "CHANGE-ME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}
