output "asg_name" {
  value = aws_autoscaling_group.this.name
}

output "security_group_id" {
  value = aws_security_group.this.id
}

output "instance_role_arn" {
  value = aws_iam_role.this.arn
}
