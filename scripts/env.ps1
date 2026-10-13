# Dot-source from a compiler checkout or unpacked toolchain bundle.
$XuEnvDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path "$XuEnvDir\src") -and (Test-Path "$XuEnvDir\..\src")) { $XuEnvDir = (Resolve-Path "$XuEnvDir\..").Path }
$env:XU_ROOT = $XuEnvDir
$env:XU_STDLIB_ROOT = "$XuEnvDir\src"
$XuEnvBin = "$XuEnvDir\bin"
$XuEnvArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
if (Test-Path "$XuEnvBin\platform\windows-$XuEnvArch") { $XuEnvBin = "$XuEnvBin\platform\windows-$XuEnvArch" }
foreach ($XuEnvPath in @("$XuEnvDir\packages", "$XuEnvDir\src")) {
    if ((Test-Path $XuEnvPath) -and (($env:XUPATH -split ';') -notcontains $XuEnvPath)) {
        $env:XUPATH = (@($XuEnvPath) + @($env:XUPATH -split ';' | Where-Object { $_ })) -join ';'
    }
}
if (($env:Path -split ';') -notcontains $XuEnvBin) { $env:Path = "$XuEnvBin;" + $env:Path }
Write-Host "Xu environment activated: $XuEnvDir" -ForegroundColor Green
