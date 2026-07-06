output "mcp_public_ip" {
  value = alicloud_instance.mcp_server.public_ip
}

output "mcp_url" {
  value = "http://${alicloud_instance.mcp_server.public_ip}:8765"
}

output "rds_endpoint" {
  value = alicloud_db_connection.cosmos.connection_string
}

output "vpc_id" {
  value = alicloud_vpc.cosmos.id
}

output "vswitch_id" {
  value = alicloud_vswitch.cosmos.id
}

output "security_group_id" {
  value = alicloud_security_group.cosmos.id
}
