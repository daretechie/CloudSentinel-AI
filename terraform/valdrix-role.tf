# Valdrix - Read-Only IAM Role for Cost Analysis
#
# This Terraform module creates an IAM role that allows Valdrix to read
# your AWS cost data. The role uses cross-account AssumeRole with
# an External ID for security.
#
# Usage:
#   module "valdrix" {
#     source      = "./valdrix"
#     external_id = "vx-YOUR_EXTERNAL_ID_HERE"
#   }
#
# After apply, copy the role_arn output to Valdrix dashboard.

variable "external_id" {
  description = "The External ID provided by Valdrix. Required for security."
  type        = string

  validation {
    condition     = can(regex("^vx-[a-f0-9]{32}$", var.external_id))
    error_message = "External ID must be in format 'vx-' followed by 32 hex characters."
  }
}

variable "valdrix_account_id" {
  description = "Valdrix's AWS Account ID (provided by Valdrix)"
  type        = string
  default     = "YOUR_VALDRIX_ACCOUNT_ID"  # Replace with actual account ID
}

# IAM Role for Valdrix
resource "aws_iam_role" "valdrix" {
  name               = "ValdrixReadOnly"
  description        = "Allows Valdrix to read cost data for analysis"
  max_session_duration = 3600  # 1 hour

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.valdrix_account_id}:root"
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
    Purpose   = "Valdrix-CostAnalysis"
    ManagedBy = "Valdrix"
  }
}

# Cost Explorer Read-Only Policy
resource "aws_iam_role_policy" "cost_explorer" {
  name = "ValdrixCostExplorerReadOnly"
  role = aws_iam_role.valdrix.id

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
  description = "The ARN of the Valdrix role. Copy this to Valdrix dashboard."
  value       = aws_iam_role.valdrix.arn
}

output "role_name" {
  description = "The name of the Valdrix role."
  value       = aws_iam_role.valdrix.name
}
