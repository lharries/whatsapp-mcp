' start-whatsapp-hidden.vbs
' Launches the whatsapp-bridge HIDDEN (no visible window) as a normal USER process.
'
' Why a hidden user process and NOT a Windows service:
'   - The Go bridge (whatsmeow) connects reliably as a USER process, but when run
'     as a LocalSystem service it does NOT open its :8080 REST port. WhatsApp Web's
'     multi-device link is bound to the interactive user context; the service
'     context never brings the REST server up. Running it as the logged-in user is
'     the only configuration that works.
'   - The bridge uses its console to draw the login QR code when WhatsApp needs to
'     be re-linked. Here the console STILL EXISTS (so the bridge runs normally) but
'     its window is hidden (Run ..., 0), so day to day you never see a stray window.
'   - The launched .bat wraps the bridge in an auto-restart loop and appends output
'     to bridge.log (UTF-8), so if a QR ever appears it is captured legibly there.
'     To scan a QR interactively, run qr-bridge.bat (a VISIBLE window).
'
' Install location:
'   This script computes the bridge directory RELATIVE TO ITS OWN LOCATION, so the
'   whole toolkit is portable: drop the "scripts" folder anywhere and it still works,
'   as long as it sits next to (or is pointed at) your whatsapp-mcp checkout.
'   You can also override the location by setting the WHATSAPP_MCP_DIR environment
'   variable to the folder that contains the "whatsapp-bridge" directory.
'
' Assumed layout (default, no env var needed):
'   <WHATSAPP_MCP_DIR>\
'     scripts\start-whatsapp-hidden.vbs   <- this file
'     scripts\start-whatsapp-bridge.bat
'     whatsapp-bridge\whatsapp-bridge.exe <- the built Go binary from upstream
'
' If your scripts live somewhere other than a "scripts" subfolder of the checkout,
' set WHATSAPP_MCP_DIR explicitly (see README / install.ps1).

Option Explicit

Dim shell, fso, envDir, scriptDir, mcpDir, batPath
Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

' 1) Prefer an explicit override via environment variable.
envDir = shell.ExpandEnvironmentStrings("%WHATSAPP_MCP_DIR%")
If envDir <> "" And envDir <> "%WHATSAPP_MCP_DIR%" And fso.FolderExists(envDir) Then
    mcpDir = envDir
Else
    ' 2) Otherwise, derive it from this script's own path.
    '    This script lives in <mcpDir>\scripts\, so the parent of the script folder
    '    is the install dir. If you placed the scripts directly in <mcpDir>, this
    '    still resolves to the folder that should contain "whatsapp-bridge".
    scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
    If fso.FolderExists(fso.BuildPath(scriptDir, "whatsapp-bridge")) Then
        ' scripts sit directly inside the install dir
        mcpDir = scriptDir
    Else
        ' scripts sit in a subfolder (the normal "scripts\" layout)
        mcpDir = fso.GetParentFolderName(scriptDir)
    End If
End If

batPath = fso.BuildPath(mcpDir, "scripts\start-whatsapp-bridge.bat")
If Not fso.FileExists(batPath) Then
    ' Fallback: allow the .bat to sit next to this script (flat layout).
    batPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "start-whatsapp-bridge.bat")
End If

' Pass the resolved install dir to the .bat via the environment so both agree on paths.
shell.Environment("PROCESS").Item("WHATSAPP_MCP_DIR") = mcpDir

' Run hidden (0) and do not wait (False).
shell.Run """" & batPath & """", 0, False
