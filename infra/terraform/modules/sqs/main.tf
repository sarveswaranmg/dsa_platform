# Matches services/exam's submissions_queue ("dsa-submissions") and
# verdicts_queue ("dsa-verdicts") — see services/exam/app/core/config.py
# and services/judge/app/config.py.

resource "aws_sqs_queue" "submissions_dlq" {
  name = "${var.name}-submissions-dlq"
  tags = var.tags
}

resource "aws_sqs_queue" "submissions" {
  name                       = "${var.name}-submissions"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.submissions_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
  tags = var.tags
}

resource "aws_sqs_queue" "verdicts_dlq" {
  name = "${var.name}-verdicts-dlq"
  tags = var.tags
}

resource "aws_sqs_queue" "verdicts" {
  name                       = "${var.name}-verdicts"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.verdicts_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
  tags = var.tags
}
