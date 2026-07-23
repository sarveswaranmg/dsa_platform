output "role_arn" {
  description = "This becomes the AWS_ROLE_ARN GitHub secret deploy.yml assumes."
  value       = aws_iam_role.this.arn
}
