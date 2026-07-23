output "alb_arn" {
  value = aws_lb.this.arn
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "security_group_id" {
  value = aws_security_group.this.id
}

# The listener services should attach their target group's rule to: HTTPS
# once TLS is enabled, otherwise plain HTTP.
output "primary_listener_arn" {
  value = local.tls_enabled ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
}

output "tls_enabled" {
  value = local.tls_enabled
}
