terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# ── Reference existing infrastructure (owned by luke_stuff/terraform) ──────────

data "aws_iam_role" "games_server" {
  name = "games-server-role"
}

# ── SSM parameter for MCP OAuth client secret ─────────────────────────────────

resource "aws_ssm_parameter" "mcp_client_secret" {
  name        = "/whatsapp-mcp/client-secret"
  type        = "SecureString"
  value       = "REPLACE_ME"
  description = "OAuth client secret for WhatsApp MCP server (claude client)"

  lifecycle {
    ignore_changes = [value]
  }
}

# ── IAM: attach a separate policy so we don't touch luke_stuff state ───────────

resource "aws_iam_policy" "mcp_ssm_read" {
  name        = "whatsapp-mcp-ssm-read"
  description = "Allow EC2 instance to read WhatsApp MCP secret from SSM"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = [aws_ssm_parameter.mcp_client_secret.arn]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "mcp_ssm_read" {
  role       = data.aws_iam_role.games_server.name
  policy_arn = aws_iam_policy.mcp_ssm_read.arn
}
