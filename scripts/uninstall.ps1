# Xu Programming Language — Windows Uninstaller
param (
    [string]$Prefix = "$HOME\.xu"
)

Write-Host "Removing Xu Development Environment from: $Prefix" -ForegroundColor Yellow

if (Test-Path $Prefix) {
    Remove-Item -Path $Prefix -Recurse -Force
    Write-Host "[OK] Removed $Prefix" -ForegroundColor Green
}

[System.Environment]::SetEnvironmentVariable("XU_ROOT", $null, [System.EnvironmentVariableTarget]::User)
[System.Environment]::SetEnvironmentVariable("XU_STDLIB_ROOT", $null, [System.EnvironmentVariableTarget]::User)
[System.Environment]::SetEnvironmentVariable("XUPATH", $null, [System.EnvironmentVariableTarget]::User)

$UserPath = [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)
if ($UserPath -like "*$Prefix\bin*") {
    $CleanPath = ($UserPath -split ";" | Where-Object { $_ -ne "$Prefix\bin" -and $_ -ne "" }) -join ";"
    [System.Environment]::SetEnvironmentVariable("Path", $CleanPath, [System.EnvironmentVariableTarget]::User)
    Write-Host "[OK] Removed from User PATH" -ForegroundColor Green
}

Write-Host "Xu has been uninstalled successfully." -ForegroundColor Green
