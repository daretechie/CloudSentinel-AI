# CloudSentinel AI - Read-Only IAM Role for Cost Analysis
#
# This Terraform module creates an IAM role that allows CloudSentinel to read
# your AWS cost data. The role uses cross-account AssumeRole with
# an External ID for security.
#
# Usage:
#   module "cloudsentinel" {
#     source      = "./cloudsentinel"
#     external_id = "cs-YOUR_EXTERNAL_ID_HERE"
#   }
#
# After apply, copy the role_arn output to CloudSentinel dashboard.

variable "external_id" {
  description = "The External ID provided by CloudSentinel. Required for security."
  type        = string

  validation {
    condition     = can(regex("^cs-[a-f0-9]{32}$", var.external_id))
    error_message = "External ID must be in format 'cs-' followed by 32 hex characters."
  }
}

variable "cloudsentinel_account_id" {
  description = "CloudSentinel's AWS Account ID (provided by CloudSentinel)"
  type        = string
  default     = "YOUR_CLOUDSENTINEL_ACCOUNT_ID"  # Replace with actual account ID
}

# IAM Role for CloudSentinel
resource "aws_iam_role" "cloudsentinel" {
  name               = "CloudSentinelReadOnly"
  description        = "Allows CloudSentinel AI to read cost data for analysis"
  max_session_duration = 3600  # 1 hour

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.cloudsentinel_account_id}:root"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.external_id
          }
        }
      }
    ]
  })

  tags = {
    Purpose   = "CloudSentinel-CostAnalysis"
    ManagedBy = "CloudSentinel"
  }
}

# Cost Explorer Read-Only Policy
resource "aws_iam_role_policy" "cost_explorer" {
  name = "CloudSentinelCostExplorerReadOnly"
  role = aws_iam_role.cloudsentinel.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CostExplorerRead"
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast",
          "ce:GetDimensionValues",
          "ce:GetTags",
          "ce:GetReservationCoverage",
          "ce:GetReservationUtilization",
          "ce:GetSavingsPlansUtilization",
          "ce:GetSavingsPlansCoverage"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2ReadOnly"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeVolumes",
          "ec2:DescribeSnapshots"
        ]
        Resource = "*"
      },
      {
        Sid    = "RDSReadOnly"
        Effect = "Allow"
        Action = [
          "rds:DescribeDBInstances",
          "rds:DescribeDBClusters"
        ]
        Resource = "*"
      }
    ]
  })
}

# Outputs
output "role_arn" {
  description = "The ARN of the CloudSentinel role. Copy this to CloudSentinel dashboard."
  value       = aws_iam_role.cloudsentinel.arn
}

output "role_name" {
  description = "The name of the CloudSentinel role."
  value       = aws_iam_role.cloudsentinel.name
}
