/**
 * MCP (Model Context Protocol) types and interfaces
 */

export interface MCPToolResponse<T = any> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

export interface MCPToolRequest {
  name: string;
  arguments: Record<string, any>;
}

export type MCPTransportType = 'stdio' | 'sse';

export interface MCPServerConfig {
  name: string;
  version: string;
  transportType: MCPTransportType;
  port?: number;
}

export interface MCPClientConfig {
  name: string;
  version: string;
  serverUrl?: string;
  command?: string;
  argList?: string[];
}
