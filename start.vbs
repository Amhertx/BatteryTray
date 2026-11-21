' 静默启动（无黑窗）
Dim fso, sh, base, pyw
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = "C:\Users\Guoba\AppData\Local\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
sh.CurrentDirectory = base
sh.Run """" & pyw & """ """ & base & "\run.pyw""", 0, False
