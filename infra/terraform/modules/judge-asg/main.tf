# Plain EC2 ASG (not ECS-on-EC2) — judge needs the real host's Docker
# socket to launch sandbox containers (DooD), and this pool runs nothing
# else, matching docs/DECISIONS.md's "dedicated node pool, nothing
# co-tenanted."
#
# KNOWN GAP: services/judge/app/sqs.py and app/s3.py always pass explicit
# aws_access_key_id/aws_secret_access_key from Settings (default "test",
# for localstack) to boto3, unlike the SES sender (which was specifically
# redesigned to fall back to the instance/task role). The instance profile
# below is provisioned correctly, but judge's boto3 clients won't actually
# use it until that same small change lands in judge's own code — until
# then, real AWS calls with the "test" placeholder credential will fail
# authentication. Flagging this rather than working around it with a static
# IAM user, which would contradict this project's "no long-lived
# credentials" posture everywhere else (OIDC, RS256, SES-via-role).

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

data "aws_region" "current" {}

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-instance"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
  tags               = var.tags
}

data "aws_iam_policy_document" "judge" {
  statement {
    sid       = "ConsumeSubmissions"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
    resources = [var.submissions_queue_arn]
  }
  statement {
    sid       = "PublishVerdicts"
    actions   = ["sqs:SendMessage"]
    resources = [var.verdicts_queue_arn]
  }
  statement {
    sid       = "ReadTestCases"
    actions   = ["s3:GetObject"]
    resources = ["${var.s3_bucket_arn}/*"]
  }
  statement {
    sid       = "PullFromEcr"
    actions   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability"]
    resources = ["*"]
  }
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "judge" {
  name   = "judge-permissions"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.judge.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  # SSM Session Manager instead of SSH — no bastion, no open port 22.
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.name}-instance"
  role = aws_iam_role.this.name
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-"
  description = "Judge worker nodes — no inbound, egress only (SQS/S3/ECR/SES)"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = var.name })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

locals {
  ecr_registry = split("/", var.ecr_repository_url)[0]
  image        = "${var.ecr_repository_url}:${var.image_tag}"

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    aws_region    = data.aws_region.current.name
    ecr_registry  = local.ecr_registry
    image         = local.image
    judge_runtime = var.judge_runtime
    environment   = merge(var.environment, { JUDGE_RUNTIME = var.judge_runtime })
  })
}

resource "aws_launch_template" "this" {
  name_prefix   = "${var.name}-"
  image_id      = data.aws_ami.al2023.id
  instance_type = var.instance_type
  user_data     = base64encode(local.user_data)

  iam_instance_profile {
    arn = aws_iam_instance_profile.this.arn
  }

  vpc_security_group_ids = [aws_security_group.this.id]

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = var.name })
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "this" {
  name                = var.name
  vpc_zone_identifier = var.private_subnet_ids
  min_size            = var.min_size
  max_size            = var.max_size
  desired_capacity    = var.desired_capacity

  launch_template {
    id      = aws_launch_template.this.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = var.name
    propagate_at_launch = true
  }
}

resource "aws_autoscaling_policy" "scale_up" {
  name                   = "${var.name}-scale-up"
  autoscaling_group_name = aws_autoscaling_group.this.name
  adjustment_type        = "ChangeInCapacity"
  policy_type            = "SimpleScaling"
  scaling_adjustment     = 2
  cooldown               = 120
}

resource "aws_autoscaling_policy" "scale_down" {
  name                   = "${var.name}-scale-down"
  autoscaling_group_name = aws_autoscaling_group.this.name
  adjustment_type        = "ChangeInCapacity"
  policy_type            = "SimpleScaling"
  scaling_adjustment     = -1
  cooldown               = 300
}

resource "aws_cloudwatch_metric_alarm" "scale_up" {
  alarm_name          = "${var.name}-queue-depth-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = var.scale_up_threshold
  alarm_description   = "Submissions backlog is growing — scale judge out."
  alarm_actions       = [aws_autoscaling_policy.scale_up.arn]

  dimensions = {
    QueueName = var.submissions_queue_name
  }
}

resource "aws_cloudwatch_metric_alarm" "scale_down" {
  alarm_name          = "${var.name}-queue-depth-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 5
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = var.scale_down_threshold
  alarm_description   = "Submissions backlog is small — scale judge in."
  alarm_actions       = [aws_autoscaling_policy.scale_down.arn]

  dimensions = {
    QueueName = var.submissions_queue_name
  }
}
