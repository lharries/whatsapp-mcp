locals {
  hostname = "34.242.181.49.nip.io"
}

output "mcp_sse_url" {
  value = "https://${local.hostname}/sse"
}

output "mcp_token_url" {
  value = "https://${local.hostname}/oauth/token"
}

output "set_secret_command" {
  description = "Run this once to store a real client secret in SSM"
  value       = "aws ssm put-parameter --name /whatsapp-mcp/client-secret --value 'YOUR_SECRET' --type SecureString --overwrite"
}

output "claude_mcp_config" {
  description = "Add this to ~/.claude.json mcpServers"
  value = jsonencode({
    whatsapp = {
      url = "https://${local.hostname}/sse"
      oauth = {
        tokenUrl     = "https://${local.hostname}/oauth/token"
        clientId     = "claude"
        clientSecret = "(value from SSM /whatsapp-mcp/client-secret)"
      }
    }
  })
}
