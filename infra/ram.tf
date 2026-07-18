resource "alicloud_ram_role" "fc_role" {
  name        = "cosmos-q-fc-role"
  document    = <<EOF
{
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "fc.aliyuncs.com"
        ]
      }
    }
  ],
  "Version": "1"
}
EOF
  description = "Role for Function Compute to access VPC resources."
  force       = true
}

resource "alicloud_ram_role_policy_attachment" "fc_vpc_policy" {
  role_name   = alicloud_ram_role.fc_role.name
  policy_name = "AliyunECSNetworkInterfaceManagementAccess"
  policy_type = "System"
}
