Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = currentDir & "\run_server.bat"

If fso.FileExists(batPath) Then
    WshShell.Run chr(34) & batPath & chr(34), 1
Else
    MsgBox "File not found: " & batPath
End If