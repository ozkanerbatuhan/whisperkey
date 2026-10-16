# Puts a whisperkey shortcut on the desktop (and, with -StartMenu, in the
# Start menu too). It launches whisperkey-silent.bat minimized, so no console
# flashes, and carries the application icon.
#
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1 -StartMenu

param([switch]$StartMenu)

$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "whisperkey-silent.bat"
$icon = Join-Path $root "src\whisperkey\assets\whisperkey.ico"

$folders = @([Environment]::GetFolderPath("Desktop"))
if ($StartMenu) { $folders += [Environment]::GetFolderPath("Programs") }

$shell = New-Object -ComObject WScript.Shell
foreach ($folder in $folders) {
    $path = Join-Path $folder "whisperkey.lnk"
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $target
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = "$icon,0"
    $lnk.WindowStyle = 7  # minimized
    $lnk.Description = "whisperkey - hold a key and talk"
    $lnk.Save()
    Write-Host "created $path"
}
