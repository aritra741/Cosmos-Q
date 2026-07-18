resource "alicloud_rds_service_linked_role" "default" {
  service_name = "AliyunServiceRoleForRdsPgsqlOnEcs"
}

resource "alicloud_db_instance" "cosmos" {
  engine           = "PostgreSQL"
  engine_version   = "15.0"
  instance_type    = var.db_instance_class
  instance_storage = 20
  vswitch_id       = alicloud_vswitch.cosmos.id
  security_ips     = ["10.0.1.0/24"]   # allow the VSwitch subnet (ECS and Function Compute)
  instance_name    = "cosmos-q-pg"
  depends_on       = [alicloud_rds_service_linked_role.default]
}



resource "alicloud_rds_account" "cosmos" {
  db_instance_id   = alicloud_db_instance.cosmos.id
  account_name     = "cosmos"
  account_password = var.db_password
  account_type     = "Super"          # Super account can CREATE EXTENSION
}



# Private connection endpoint for ECS-to-RDS traffic

