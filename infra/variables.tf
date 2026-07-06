variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "access_key" {
  type      = string
  sensitive = true
}

variable "secret_key" {
  type      = string
  sensitive = true
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "qwen_api_key" {
  type      = string
  sensitive = true
}

variable "git_repo_url" {
  type        = string
  description = "The public Git repository URL for COSMOS-Q to clone and build on ECS"
}

variable "instance_type" {
  type    = string
  default = "ecs.e-c1m2.large"
}

variable "db_instance_class" {
  type    = string
  default = "pg.n2.small.1"
}

