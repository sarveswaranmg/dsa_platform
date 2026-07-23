output "cluster_id" {
  value = aws_ecs_cluster.this.id
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "cloud_map_namespace_id" {
  value = aws_service_discovery_private_dns_namespace.this.id
}

output "cloud_map_namespace_name" {
  value = aws_service_discovery_private_dns_namespace.this.name
}
