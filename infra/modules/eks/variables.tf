variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "nodes_security_group_id" {
  type = string
}

variable "kubernetes_version" {
  type    = string
  default = "1.33"
}

variable "instance_types" {
  type    = list(string)
  default = ["t3.medium"]
}

variable "desired_nodes" {
  type    = number
  default = 2
}

variable "min_nodes" {
  type    = number
  default = 1
}

variable "max_nodes" {
  type    = number
  default = 4
}
