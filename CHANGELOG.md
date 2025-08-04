# WhatsApp MCP Server - Changelog

## [Unreleased] - 2025-08-03

### ✨ Added Features

#### Status Monitoring System
- **MCP Resource**: `whatsapp://sync-status` - JSON resource providing real-time bridge and sync status
- **MCP Tool**: `get_sync_status()` - Interactive tool for comprehensive status checking
- **Web Dashboard**: `http://localhost:8080/status` - HTML dashboard with auto-refresh
- **HTML UI Resource**: `whatsapp://status-ui` - Rich HTML status display for MCP clients

#### Status Data Provided
- Bridge process status (running/stopped)
- WhatsApp authentication state
- API responsiveness
- Database statistics (message count, chat count, size)
- Last sync timestamp
- Error reporting and troubleshooting

### 🔧 Enhanced Features

#### Bridge Management
- **Automatic Bridge Startup**: All MCP tools now automatically start the bridge if not running
- **Enhanced Error Handling**: Improved error messages with troubleshooting steps
- **QR Code Integration**: Status API includes QR code availability for authentication
- **Resource URI Compliance**: Fixed MCP resource URIs to use proper `whatsapp://` scheme

#### Web Interface
- **Status Endpoint**: Added `/api/status` for programmatic status access
- **Dashboard UI**: Added `/status` endpoint serving interactive status page
- **Real-time Updates**: JavaScript auto-refresh every 30 seconds
- **Visual Indicators**: Color-coded status badges and metrics

### 🐛 Bug Fixes

#### Critical Fixes
- **Auto-startup Failure**: Fixed Go compilation error preventing bridge startup
  - **Issue**: Unused `qrCode` variable in `/api/status` handler
  - **Fix**: Added QR code information to status response
- **MCP Resource Validation**: Fixed resource URI validation errors
  - **Issue**: Simple string URIs not accepted by MCP framework
  - **Fix**: Changed to proper URI scheme (`whatsapp://sync-status`)

#### Decorator Consistency
- **Status Tools**: Added missing `@with_bridge_check` decorators
  - Fixed `get_sync_status()` tool
  - Fixed `check_bridge_status()` tool
- **Bridge Checking**: All tools now consistently attempt bridge startup

### 🏗️ Technical Improvements

#### Code Organization
- **Import Management**: Cleaned up unused MCP-UI SDK imports
- **Fallback Implementation**: Created HTML-based UI as fallback for missing MCP-UI SDK
- **Error Handling**: Enhanced error reporting with structured responses

#### Documentation
- **Status Examples**: Created comprehensive status monitoring examples
- **Usage Guide**: Documented all four status monitoring approaches
- **Troubleshooting**: Added bridge startup and authentication guides

### 📋 Implementation Details

#### Files Modified
- `whatsapp-mcp-server/main.py`: Added status monitoring tools and resources
- `whatsapp-mcp-server/pyproject.toml`: Managed MCP-UI SDK dependencies
- `whatsapp-bridge/main.go`: Fixed compilation error and enhanced status API
- `whatsapp-bridge/status.html`: Created web dashboard interface

#### New Features Architecture
1. **JSON Resource**: Static status data for reference
2. **Interactive Tool**: Dynamic status checking with bridge management
3. **Web Dashboard**: Visual monitoring interface
4. **HTML Resource**: Rich client-side status display

### 🧪 Testing

#### Verified Functionality
- ✅ Automatic bridge startup when stopped
- ✅ Bridge compilation and runtime
- ✅ Status monitoring across all interfaces
- ✅ QR code authentication flow
- ✅ Error handling and recovery
- ✅ Database statistics accuracy

#### Browser Testing
- ✅ Web dashboard responsive design
- ✅ Auto-refresh functionality
- ✅ Real-time status updates
- ✅ Error state display

### 🔄 Migration Notes

#### For Existing Users
- No breaking changes to existing MCP tools
- All existing functionality preserved
- New status monitoring features are additive
- Bridge auto-startup improves user experience

#### Configuration
- No configuration changes required
- Status dashboard available immediately at `http://localhost:8080/status`
- MCP resources available in Claude Desktop resource list

---

## Previous Versions

### [v0.1.0] - Initial Release
- Basic WhatsApp MCP server functionality
- Message and chat management tools
- Bridge process management
- Authentication via QR codes