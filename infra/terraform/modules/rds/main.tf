# One RDS instance, two logical databases (exam, question) + one role per
# database, created via the postgresql provider rather than a second
# aws_db_instance per service — see infra/terraform/README.md for why.
#
# NOTE: the postgresql provider below is configured against THIS module's
# own aws_db_instance, so it's declared here rather than passed in from the
# root — this module is only ever instantiated once, so there's no reuse
# concern with keeping the provider config local to it. Terraform must be
# able to reach the instance's endpoint on 5432 to run the postgresql_*
# resources; see the README for the two-phase-apply note if it isn't.

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.private_subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-"
  description = "Postgres access for ${var.name}"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = var.name })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  for_each                     = toset(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_db_instance" "this" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "16"

  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage
  storage_encrypted = true
  multi_az          = var.multi_az

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]

  username                    = "postgres"
  manage_master_user_password = true

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name}-final"

  backup_retention_period = 7
  tags                    = var.tags
}

data "aws_secretsmanager_secret_version" "master" {
  secret_id = aws_db_instance.this.master_user_secret[0].secret_arn
}

provider "postgresql" {
  host            = aws_db_instance.this.address
  port            = aws_db_instance.this.port
  username        = aws_db_instance.this.username
  password        = jsondecode(data.aws_secretsmanager_secret_version.master.secret_string)["password"]
  sslmode         = "require"
  connect_timeout = 15
  superuser       = false
}

resource "random_password" "db" {
  for_each = toset(var.databases)
  length   = 32
  special  = false
}

resource "postgresql_role" "this" {
  for_each = toset(var.databases)
  name     = each.value
  login    = true
  password = random_password.db[each.value].result
}

resource "postgresql_database" "this" {
  for_each = toset(var.databases)
  name     = each.value
  owner    = postgresql_role.this[each.value].name
}

resource "aws_secretsmanager_secret" "database_url" {
  for_each = toset(var.databases)
  name     = "${var.name}/${each.value}-database-url"
  tags     = var.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  for_each      = toset(var.databases)
  secret_id     = aws_secretsmanager_secret.database_url[each.value].id
  secret_string = "postgresql+asyncpg://${postgresql_role.this[each.value].name}:${random_password.db[each.value].result}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${postgresql_database.this[each.value].name}"
}
