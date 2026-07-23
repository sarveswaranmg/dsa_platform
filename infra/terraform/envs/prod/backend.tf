# State backend: bucket + DynamoDB lock table are a documented prerequisite
# (infra/terraform/README.md), created once, outside this config — you
# can't have Terraform manage the backend it also uses to store its own
# state without a bootstrapping chicken-and-egg problem. Replace the
# placeholder values below with your real bucket/table before `terraform init`.
terraform {
  backend "s3" {
    bucket         = "dsa-platform-terraform-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "dsa-platform-terraform-locks"
    encrypt        = true
  }
}
