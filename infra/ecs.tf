data "alicloud_images" "ubuntu" {
  owners      = "system"
  name_regex  = "^ubuntu_22_04_x64"
  most_recent = true
}

resource "alicloud_instance" "mcp_server" {
  instance_name              = "cosmos-q-mcp"
  instance_type              = var.instance_type
  image_id                   = data.alicloud_images.ubuntu.images[0].id
  security_groups            = [alicloud_security_group.cosmos.id]
  vswitch_id                 = alicloud_vswitch.cosmos.id
  internet_max_bandwidth_out = 10   # gives it a public IP

  password                   = var.ecs_password

  user_data = base64encode(templatefile("${path.module}/scripts/ecs_bootstrap.sh.tpl", {
    git_repo_url = var.git_repo_url
    qwen_api_key = var.qwen_api_key
    pg_host      = alicloud_db_instance.cosmos.connection_string
    pg_dsn       = "postgresql://cosmos:${var.db_password}@${alicloud_db_instance.cosmos.connection_string}:5432/cosmos_q"
  }))

  depends_on = [alicloud_db_instance.cosmos]
}
