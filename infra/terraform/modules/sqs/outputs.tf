output "submissions_queue_url" {
  value = aws_sqs_queue.submissions.url
}

output "submissions_queue_arn" {
  value = aws_sqs_queue.submissions.arn
}

output "submissions_queue_name" {
  value = aws_sqs_queue.submissions.name
}

output "verdicts_queue_url" {
  value = aws_sqs_queue.verdicts.url
}

output "verdicts_queue_arn" {
  value = aws_sqs_queue.verdicts.arn
}

output "verdicts_queue_name" {
  value = aws_sqs_queue.verdicts.name
}
