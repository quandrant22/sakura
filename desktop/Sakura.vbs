' Запуск Сакуры без окна консоли: двойной щелчок или ярлык «Sakura».
' Проверки, сборка и запуск — в tools\launch.ps1; ошибки показываются диалогом.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
script = here & "\tools\launch.ps1"
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """", 0, False
