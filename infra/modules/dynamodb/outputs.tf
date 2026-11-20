output "table_names" {
  value = merge(
    { for k, t in aws_dynamodb_table.service : k => t.name },
    {
      sagas           = aws_dynamodb_table.sagas.name
      "feature-flags" = aws_dynamodb_table.feature_flags.name
    }
  )
}

output "table_arns" {
  value = concat(
    [for t in aws_dynamodb_table.service : t.arn],
    [aws_dynamodb_table.sagas.arn, aws_dynamodb_table.feature_flags.arn]
  )
}

output "feature_flags_table_name" {
  value = aws_dynamodb_table.feature_flags.name
}
