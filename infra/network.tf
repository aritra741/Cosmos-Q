resource "alicloud_vpc" "cosmos" {
  vpc_name   = "cosmos-q-vpc"
  cidr_block = "10.0.0.0/16"
}

data "alicloud_zones" "available" {
  available_resource_creation = "VSwitch"
}

resource "alicloud_vswitch" "cosmos" {
  vpc_id       = alicloud_vpc.cosmos.id
  cidr_block   = "10.0.1.0/24"
  zone_id      = data.alicloud_zones.available.zones[0].id
  vswitch_name = "cosmos-q-vsw"
}

resource "alicloud_security_group" "cosmos" {
  security_group_name = "cosmos-q-sg"
  vpc_id              = alicloud_vpc.cosmos.id
}

# SSH (restrict to your IP in production)
resource "alicloud_security_group_rule" "ssh" {
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "22/22"
  security_group_id = alicloud_security_group.cosmos.id
  cidr_ip           = "0.0.0.0/0"
}

# MCP server port
resource "alicloud_security_group_rule" "mcp" {
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "8765/8765"
  security_group_id = alicloud_security_group.cosmos.id
  cidr_ip           = "0.0.0.0/0"
}
