Option Explicit

Dim shell, files, appPath, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
appPath = files.GetParentFolderName(WScript.ScriptFullName) & "\app.py"
shell.CurrentDirectory = files.GetParentFolderName(WScript.ScriptFullName)
command = "pyw -3 """ & appPath & """"

On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
    Err.Clear
    shell.Run "pythonw """ & appPath & """", 0, False
End If
If Err.Number <> 0 Then
    MsgBox "Could not start Takeout Organizer. For the source version, install Python 3.10 or newer and enable the Python Launcher, then try again.", vbExclamation, "Takeout Organizer"
End If
On Error GoTo 0
