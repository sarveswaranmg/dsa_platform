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

**Required GitHub secrets** (Settings → Secrets and variables → Actions →
repository secrets) — everything `.github/workflows/deploy.yml` needs, each
sourced from a `terraform output` after `apply`:

| Secret | Value |
|---|---|
| `AWS_ROLE_ARN` | `terraform output -raw github_actions_role_arn` |
| `AWS_REGION` | Whatever you set `aws_region` to (default `us-east-1`) |
| `ECS_CLUSTER_NAME` | `terraform output -raw ecs_cluster_name` |
| `PRIVATE_SUBNET_IDS` | `terraform output -json private_subnet_ids` — comma-join the list (e.g. `subnet-aaa,subnet-bbb`) |
| `EXAM_MIGRATE_SECURITY_GROUP_ID` | `terraform output -raw exam_migrate_security_group_id` |
| `QUESTION_MIGRATE_SECURITY_GROUP_ID` | `terraform output -raw question_migrate_security_group_id` |
| `S3_FRONTEND_BUCKET` | `terraform output -raw frontend_bucket_name` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `terraform output -raw cloudfront_distribution_id` |
| `VITE_API_BASE_URL` | `https://<api_domain>` if `domain_name` is set, else `http://<alb_dns_name>` (both from `terraform output`) |

`deploy.yml` triggers via `workflow_run` after `ci.yml` completes
successfully on `main` (or manually via `workflow_dispatch`) and runs four
jobs in sequence: build+push all 4 images to ECR, run the exam/question
migrate tasks and wait for them, roll gateway/exam/question to the new
image, then build the frontend with `VITE_API_BASE_URL` and sync+invalidate
CloudFront. See the workflow file itself and `scripts/run-migrate-task.sh` /
`scripts/deploy-ecs-service.sh` for the exact mechanics.

## Deploying application code

Once the infrastructure above exists (`terraform apply` done, Google OIDC
secrets populated, the 9 GitHub secrets set), here's the full path from a
merged PR to a live deploy:

1. **First deploy only — bootstrap ECS with a real image once, manually.**
   The ECS services `terraform apply` created reference `var.image_tag`
   (`"initial"` by default) — an image that doesn't exist, so they'll show 0
   running tasks until something pushes a real one. `deploy.yml` itself is
   what does this normally, but on a brand-new environment there's a
   chicken-and-egg gap (services aren't healthy yet, but that's fine —
   `deploy.yml` doesn't require them to be healthy first, it just registers
   a new task definition revision and updates the service regardless).
   Simplest path: just merge to `main` once with CI passing — `deploy.yml`
   builds and pushes real images and rolls the services to them, same as
   every subsequent deploy. No separate manual bootstrap actually needed.

2. **Normal deploy flow**: merge a PR to `main` → `ci.yml` runs (`make
   lint`, `make test`) → on success, `deploy.yml` fires automatically:
   - **`build-and-push`** (parallel, one per service): builds
     `services/<name>/Dockerfile`, pushes to ECR tagged with the commit SHA.
     Watch this job if a build itself is broken (Dockerfile change, missing
     dependency) — nothing below it runs until all four succeed.
   - **`migrate`**: registers a fresh `exam-migrate`/`question-migrate` task
     definition revision pointing at the new `exam`/`question` image, runs
     each via `aws ecs run-task`, and waits for it to stop. **If a migration
     fails (non-zero exit), the job fails here and `deploy-services` never
     runs** — the currently-running gateway/exam/question tasks are
     untouched, so the app keeps serving traffic on the old code/schema.
     Check the failed migration's CloudWatch log group (`/ecs/exam-migrate`
     or `/ecs/question-migrate`) for the Alembic error, fix it, and
     re-push — safe to re-run, migrations are idempotent (`alembic upgrade
     head`).
   - **`deploy-services`** (parallel, one per service): registers a new task
     definition revision per service, `update-service --force-new-deployment`,
     waits for `services-stable`. This is what actually performs the rolling
     deploy — ECS starts new tasks on the new revision, health-checks them
     via the target group (gateway) or Cloud Map, and only then drains the
     old ones.
   - **`deploy-frontend`**: builds `frontend/` with `VITE_API_BASE_URL`
     baked in, `aws s3 sync --delete`, then invalidates the whole CloudFront
     distribution (`/*`) so the new bundle is served immediately instead of
     waiting out cache TTLs.

3. **Verifying a deploy landed**: `curl http://<alb_dns_name>/healthz` (or
   `https://<api_domain>/healthz` if TLS is on) should hit gateway; the
   CloudFront domain (or `domain_name`) should serve the updated frontend
   immediately post-invalidation. `aws ecs describe-services --cluster
   <cluster> --services gateway exam question` shows each service's running
   task definition revision if you want to confirm exactly what's live.

4. **Manual redeploy** (no new commit — e.g. retrying after a transient AWS
   throttling error): trigger `deploy.yml` via `workflow_dispatch` from the
   Actions tab. It deploys whatever's on `main`'s tip.

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
- **`deploy.yml` doesn't redeploy judge's EC2 ASG.** Its rolling-deploy step
  only covers ECS services (gateway/exam/question) — judge runs on a plain
  EC2 ASG, and "update the service" doesn't map the same way there (no ECS
  service to roll). `build-and-push` does push a new judge image to ECR,
  but nothing currently triggers the ASG to pick it up (new instances
  launched later will `docker pull` it via `user_data`, but already-running
  instances won't restart their container automatically). An `aws
  autoscaling start-instance-refresh` step is a reasonable follow-up, not
  yet built.
