# Terraform — production AWS deployment

Provisions the AWS infrastructure for `dsa_platform`'s production environment:
VPC, RDS Postgres, ElastiCache Redis, SQS, S3 (submissions + frontend),
CloudFront, ECR, an ECS Fargate cluster (gateway/exam/question), one-off
migration ECS tasks, a dedicated EC2 ASG for judge, Secrets Manager entries,
and the IAM role GitHub Actions assumes to deploy.

Terraform 1.7+, AWS provider `~> 5.0`.

## Layout

```
infra/terraform/
  modules/       Reusable pieces — one AWS concern each (see each module's
                 own comments for what it provisions and why).
  envs/prod/     The only root module today. Calls every module and wires
                 outputs to inputs.
```

`modules/ecs-service` and `modules/ecs-migrate-task` are each called more
than once (gateway/exam/question; exam-migrate/question-migrate) — see
`envs/prod/main.tf`.

## Prerequisites

1. **AWS credentials** with sufficient permissions, configured however you
   normally do (`aws configure`, an SSO profile, etc.) — Terraform uses the
   AWS CLI's standard credential chain.

2. **State backend** (S3 bucket + DynamoDB lock table) — created once,
   *outside* this config, to avoid the chicken-and-egg problem of Terraform
   managing the backend it also stores its own state in:

   ```
   aws s3api create-bucket --bucket dsa-platform-terraform-state \
     --region us-east-1
   aws s3api put-bucket-versioning --bucket dsa-platform-terraform-state \
     --versioning-configuration Status=Enabled
   aws s3api put-bucket-encryption --bucket dsa-platform-terraform-state \
     --server-side-encryption-configuration \
     '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

   aws dynamodb create-table --table-name dsa-platform-terraform-locks \
     --attribute-definitions AttributeName=LockID,AttributeType=S \
     --key-schema AttributeName=LockID,KeyType=HASH \
     --billing-mode PAY_PER_REQUEST
   ```

   Update the bucket/table names in `envs/prod/backend.tf` if you used
   different ones.

3. **`terraform.tfvars`** — copy `envs/prod/terraform.tfvars.example` and
   fill in `github_org`/`github_repo`/`ses_from_address` at minimum.

## First run

```
cd envs/prod
terraform init
terraform plan
terraform apply
```

**Two things about the very first apply:**

- **No Docker images exist in ECR yet.** This config creates the ECR repos
  and ECS services in the same apply, referencing `var.image_tag` (default
  `"initial"`). The services will show 0 running tasks until you push a real
  image — that's expected. `modules/ecs-service`'s task definition has
  `lifecycle { ignore_changes = [task_definition] }`, so once the deploy
  pipeline (`deploy.yml`) registers new task definitions and updates the
  service directly, Terraform will never try to revert that on a later
  `apply`.
- **The `rds` module's `postgresql` provider connects to the real RDS
  instance** to create the `exam`/`question` databases and roles — this
  requires network reachability from wherever you run `terraform apply` to
  the instance on port 5432. If you're applying from outside the VPC (a
  laptop, a non-VPC CI runner) and RDS is fully private, the first apply may
  need to run from inside the VPC (a bastion, SSM port-forwarding, or a
  temporary CI runner in the VPC) or you'll see connection timeouts on the
  `postgresql_*` resources specifically — every other resource will apply
  fine independently. A two-step `apply` (`-target=module.vpc
  -target=module.secrets -target=module.rds` first, then a full `apply`) is
  a normal, expected way to sequence this if you hit ordering issues.

## Populating real secrets

`modules/secrets` creates two kinds of Secrets Manager entries:

- **Terraform-generated** (RS256 keypair, RDS per-database passwords) —
  fully automatic, nothing to do.
- **Shells with a `CHANGE-ME` placeholder** (Google OIDC client ID/secret,
  redirect URI) — Terraform can't generate these; a human creates the OAuth
  client in [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
  After `apply`, populate the real values:

  ```
  aws secretsmanager put-secret-value \
    --secret-id dsa-platform-prod/google-client-id \
    --secret-string "<real client id>"
  # ...same for google-client-secret and google-redirect-uri
  ```

  Terraform will never overwrite these again (`lifecycle.ignore_changes` on
  `secret_string`) — safe to `apply` repeatedly without clobbering them.

  `terraform output secrets_needing_manual_population` lists the exact ARNs.

## TLS / custom domain

`domain_name` defaults to `""`: the ALB is HTTP-only and CloudFront uses its
default `*.cloudfront.net` certificate — `terraform apply` works today with
no domain prerequisites. Once you own a domain and its Route53 hosted zone
is delegated, set `domain_name` and `route53_zone_id` in `terraform.tfvars`
and re-apply — this adds ACM certificates (API domain in the main region,
frontend domain in us-east-1, as CloudFront requires), Route53 records, and
switches the ALB's default listener to redirect HTTP → HTTPS. No
restructuring needed either way.

## GitHub Actions deploy role

`modules/github-oidc` creates an IAM OIDC provider trusting
`token.actions.githubusercontent.com` and a role GitHub Actions assumes via
`AssumeRoleWithWebIdentity` — no long-lived AWS keys stored in GitHub. The
trust policy restricts assumption to `refs/heads/main` in the configured
`github_org`/`github_repo`.

**Required GitHub secret** (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `AWS_ROLE_ARN` | `terraform output github_actions_role_arn` |

(`deploy.yml`, which assumes this role, is a separate CI/CD slice — this
just provisions the role it needs. Additional secrets `deploy.yml` itself
needs, if any beyond `AWS_ROLE_ARN` and the region, will be documented here
alongside that workflow.)

## Known gaps / follow-ups

Flagging these explicitly rather than silently working around them:

- **`services/judge/app/sqs.py` and `app/s3.py` always pass explicit
  `aws_access_key_id`/`aws_secret_access_key` from `Settings`** (default
  `"test"`, for localstack) to `boto3.client(...)`. `modules/judge-asg`
  correctly provisions an IAM instance profile with the right permissions,
  but judge's boto3 clients won't actually use it until that code is
  changed to omit explicit credentials — the same small change
  `SesEmailSender` already got (see `services/exam/app/notifications/ses_sender.py`).
  Until then, judge running against this infrastructure will fail AWS auth
  with the literal string `"test"` as a credential. Not a security hole
  (it just won't work), but a real follow-up.
- **The sandbox runner images** (`dsa-judge-python:3.12`, `-java:21`,
  `-cpp:13` — see `services/judge/runners/`, built by `make judge-images`)
  aren't provisioned an ECR repo here (`modules/ecr` only covers the 4
  *service* images: gateway, exam, question, judge). judge's EC2 instances
  currently have no way to obtain them in prod. Extending `modules/ecr`'s
  `repository_names` and adding a build/push step for these three images to
  the deploy pipeline is a follow-up, not yet done.
- **`GOOGLE_REDIRECT_URI`** is wired end-to-end (Secrets Manager, task env)
  but isn't read by any application code path today — the app's Google
  sign-in uses Google Identity Services' client-side ID-token flow, which
  needs an authorized JavaScript origin, not a redirect URI. It's here to
  match `CLAUDE.md`'s checklist wording and be ready if a server-side flow
  is ever added.
- **The frontend's static bundle (`modules/frontend-cdn`) is single-origin
  S3+CloudFront.** `frontend/src`'s API calls are same-origin relative paths
  today (correct for the `frontend/Dockerfile` nginx-proxy prod path) — that
  does *not* work unmodified via CloudFront alone, since there's no
  server-side proxy layer here. Wiring `VITE_API_BASE_URL` into the actual
  fetch calls (cross-origin, direct to the ALB) plus gateway's
  `CORS_ORIGINS`, is the CI/CD deploy slice's job.
