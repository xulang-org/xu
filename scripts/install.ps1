# Xu Programming Language — Windows Development Environment Installer
# Supports offline installation (from unpacked bundle) and online installation.

[CmdletBinding()]
param (
    [string]$Prefix = $(if ($env:XU_INSTALL_DIR) { $env:XU_INSTALL_DIR } else { "$HOME\.xu" }),
    [string]$Version = "",
    [switch]$NoModifyPath = $false
)

$ErrorActionPreference = "Stop"

# Enable TLS 1.2 (required for downloading from GitHub on Windows PowerShell 5.1)
try {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
} catch {}

function Write-Color([string]$Text, [ConsoleColor]$Color) {
    Write-Host $Text -ForegroundColor $Color
}

Write-Color @"
  __  __
  \ \/ /   _   _
   \  /   | | | |   Xu Programming Language
   /  \   | |_| |   Fast, Safe, GC-Free Systems Language
  /_/\_\   \__,_|   Windows Development Environment Installer
"@ -Color Cyan

# Detect Windows architecture safely across PowerShell 5.1 (.NET Framework) and PowerShell 7+ (.NET Core)
$Arch = $null
try {
    $osArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    if ($null -ne $osArch) {
        $Arch = $osArch.ToString().ToLowerInvariant()
    }
} catch {}

if (-not $Arch) {
    $rawArch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($rawArch -match "ARM64") {
        $Arch = "arm64"
    } elseif ($rawArch -match "AMD64|x86_64|x64") {
        $Arch = "x64"
    } elseif ([System.Environment]::Is64BitOperatingSystem) {
        $Arch = "x64"
    } else {
        $Arch = if ($rawArch) { $rawArch.ToLowerInvariant() } else { "x64" }
    }
}

if ($Arch -notin @("x64", "arm64")) { throw "Unsupported Windows architecture: $Arch (Xu currently supports x64 and arm64 on Windows)" }
$Platform = "windows-$Arch"
$Prefix = [System.IO.Path]::GetFullPath($Prefix)

Write-Color "[INFO] Detected Windows Architecture: $Arch ($Platform)" -Color Blue
Write-Color "[INFO] Target Install Directory: $Prefix" -Color Blue

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$TempZip = $null
$TempExtract = $null
try {
$SourceDir = $null
if (-not $Version) {
    $Version = "0.8.12"
    foreach ($VersionFile in @("$ScriptDir\VERSION", "$ScriptDir\..\VERSION")) {
        if (Test-Path $VersionFile) { $Version = (Get-Content $VersionFile -Raw).Trim(); break }
    }
    # If downloading online and VERSION file absent, try querying latest official release
    if (-not (Test-Path "$ScriptDir\VERSION") -and -not (Test-Path "$ScriptDir\..\VERSION")) {
        try {
            $headers = @{ "User-Agent" = "xu-installer" }
            $latest = Invoke-RestMethod -Uri "https://api.github.com/repos/xulang-org/xu/releases/latest" -Headers $headers -TimeoutSec 3 -ErrorAction SilentlyContinue -UseBasicParsing
            if ($latest.tag_name -match '^v?(\d+\.\d+\.\d+)$') {
                $Version = $Matches[1]
            }
        } catch {}
    }
}

if ((Test-Path "$ScriptDir\bin") -and (Test-Path "$ScriptDir\src")) {
    $SourceDir = $ScriptDir
    Write-Color "[INFO] Using local offline distribution files from: $SourceDir" -Color Blue
} elseif ((Test-Path "$ScriptDir\..\bin") -and (Test-Path "$ScriptDir\..\src")) {
    $SourceDir = Resolve-Path "$ScriptDir\.."
    Write-Color "[INFO] Using repository root distribution files from: $SourceDir" -Color Blue
}

if (-not $SourceDir) {
    $DownloadBase = if ($env:XU_DOWNLOAD_URL) { $env:XU_DOWNLOAD_URL.TrimEnd('/') } else { "https://github.com/xulang-org/xu/releases/download" }
    $DownloadUrl = "$DownloadBase/v$Version/xu-v$Version-$Platform.zip"
    $TempZip = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "xu_install_" + [System.Guid]::NewGuid().ToString() + ".zip")
    $TempExtract = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "xu_install_" + [System.Guid]::NewGuid().ToString())

    Write-Color "[INFO] Downloading $DownloadUrl..." -Color Blue
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $TempZip -UseBasicParsing

    Write-Color "[INFO] Extracting bundle..." -Color Blue
    Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force
    Remove-Item $TempZip -Force

    $SourceDir = "$TempExtract\xu-v$Version"
    if (-not (Test-Path $SourceDir)) {
        $SourceDir = "$TempExtract\xu"
        if (-not (Test-Path $SourceDir)) { $SourceDir = $TempExtract }
    }
}

if (-not (Test-Path "$SourceDir\src" -PathType Container) -or -not (Test-Path "$SourceDir\VERSION" -PathType Leaf)) {
    throw "Invalid Xu distribution: src/ or VERSION missing."
}
if (Test-Path "$SourceDir\TARGET") {
    $BundleTarget = (Get-Content "$SourceDir\TARGET" -Raw).Trim()
    if ($BundleTarget -ne $Platform -and $BundleTarget -ne "devkit-all") { throw "Bundle target $BundleTarget does not match host $Platform." }
}
$BinarySource = "$SourceDir\bin"
if (Test-Path "$BinarySource\platform\$Platform") { $BinarySource = "$BinarySource\platform\$Platform" }
if (-not (Test-Path "$BinarySource\xu.exe" -PathType Leaf)) { throw "Distribution compiler missing: $BinarySource\xu.exe" }
& "$BinarySource\xu.exe" --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Distribution compiler cannot run on $Platform." }
if ($Prefix -eq (Resolve-Path $SourceDir).Path) { throw "Use env.ps1 to activate a distribution in place; choose a different install directory." }

if (-not (Test-Path $Prefix)) {
    New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
}

# 1. Binaries
Write-Color "[INFO] Copying toolchain binaries..." -Color Blue
$BinDest = "$Prefix\bin"
if (-not (Test-Path $BinDest)) { New-Item -ItemType Directory -Path $BinDest -Force | Out-Null }

if (Test-Path "$SourceDir\bin\platform\$Platform") {
    Copy-Item -Path "$SourceDir\bin\platform\$Platform\*" -Destination $BinDest -Recurse -Force
} elseif (Test-Path "$SourceDir\bin") {
    $Tools = @("xu", "xu-doctor", "xu-fmt", "xu-doc", "xu-map", "xu-desktop", "xu-native")
    foreach ($tool in $Tools) {
        if (Test-Path "$SourceDir\bin\$tool.exe") {
            Copy-Item -Path "$SourceDir\bin\$tool.exe" -Destination $BinDest -Force
        } elseif (Test-Path "$SourceDir\bin\$tool") {
            Copy-Item -Path "$SourceDir\bin\$tool" -Destination $BinDest -Force
        }
    }
}

# 2. Standard library (src/)
Write-Color "[INFO] Copying standard library (src/)..." -Color Blue
$SrcDest = "$Prefix\src"
if (Test-Path $SrcDest) { Remove-Item -Path $SrcDest -Recurse -Force }
Copy-Item -Path "$SourceDir\src" -Destination $Prefix -Recurse -Force

# 3. Official drivers (packages/)
$PackagesSource = $env:XU_PACKAGES_ROOT
if (-not $PackagesSource) {
    foreach ($Candidate in @("$SourceDir\packages", "$SourceDir\..\packages", "$SourceDir\..\xu-packages")) {
        if (Test-Path $Candidate -PathType Container) { $PackagesSource = $Candidate; break }
    }
}
if ($env:XU_PACKAGES_ROOT -and -not (Test-Path $PackagesSource -PathType Container)) {
    throw "XU_PACKAGES_ROOT does not exist: $PackagesSource"
}
if ($PackagesSource) {
    Write-Color "[INFO] Copying external modules from: $PackagesSource" -Color Blue
    $PkgDest = "$Prefix\packages"
    New-Item -ItemType Directory -Path $PkgDest -Force | Out-Null
    $RootModule = Test-Path "$PackagesSource\xu.xun"
    if ($RootModule) { Copy-Item "$PackagesSource\xu.xun" -Destination $PkgDest -Force }
    Get-ChildItem $PackagesSource -Directory | Where-Object {
        (Test-Path "$($_.FullName)\xu.xun") -or ($RootModule -and (Get-ChildItem $_.FullName -Filter "*.xu" -File))
    } | ForEach-Object {
        Copy-Item $_.FullName -Destination $PkgDest -Recurse -Force
    }
} else {
    Write-Color "[INFO] External driver repository absent; core toolchain installed." -Color Blue
}

# 4. Include headers
if (Test-Path "$SourceDir\include") {
    Write-Color "[INFO] Copying native headers (include/)..." -Color Blue
    $IncDest = "$Prefix\include"
    if (Test-Path $IncDest) { Remove-Item -Path $IncDest -Recurse -Force }
    Copy-Item -Path "$SourceDir\include" -Destination $Prefix -Recurse -Force
}

# 5. Editors
$VscodeSource = $env:XU_VSCODE_ROOT
if (-not $VscodeSource) {
    foreach ($Candidate in @("$SourceDir\..\vscode-xu", "$SourceDir\editors\vscode", "$SourceDir\..\vscode", "$SourceDir\..\xu-vscode")) {
        if (Test-Path $Candidate -PathType Container) { $VscodeSource = $Candidate; break }
    }
}
if ($env:XU_VSCODE_ROOT -and -not (Test-Path $VscodeSource -PathType Container)) {
    throw "XU_VSCODE_ROOT does not exist: $VscodeSource"
}
$VsixFile = $null
if ($VscodeSource) {
    $Extension = Get-Content "$VscodeSource\package.json" -Raw | ConvertFrom-Json
    if ($Extension.name -notmatch '^[A-Za-z0-9_-]+$' -or $Extension.version -notmatch '^\d+\.\d+\.\d+([-+][A-Za-z0-9.+-]+)?$') {
        throw "Invalid VS Code extension name/version: $VscodeSource\package.json"
    }
    $CurrentVsix = "$($Extension.name)-$($Extension.version).vsix"
    $EdDest = "$Prefix\editors\vscode"
    Write-Color "[INFO] Copying VS Code extension from: $VscodeSource" -Color Blue
    New-Item -ItemType Directory -Path $EdDest -Force | Out-Null
    foreach ($Resource in @("package.json", "language-configuration.json", "README.md", $CurrentVsix)) {
        if (Test-Path "$VscodeSource\$Resource" -PathType Leaf) {
            Copy-Item "$VscodeSource\$Resource" -Destination "$EdDest\$Resource" -Force
        }
    }
    if (Test-Path "$VscodeSource\$CurrentVsix" -PathType Leaf) {
        $VsixFile = Get-Item "$EdDest\$CurrentVsix"
    }
} else {
    Write-Color "[INFO] VS Code extension repository absent; core toolchain installed." -Color Blue
}

# 6. Examples
$ExSrc = "$SourceDir\examples"
if (-not (Test-Path $ExSrc) -and $env:XU_EXAMPLES_ROOT) { $ExSrc = "$env:XU_EXAMPLES_ROOT\examples" }
if (Test-Path $ExSrc) {
    Write-Color "[INFO] Copying official examples..." -Color Blue
    $ExDest = "$Prefix\examples"
    if (Test-Path $ExDest) { Remove-Item -Path $ExDest -Recurse -Force }
    Copy-Item -Path $ExSrc -Destination $ExDest -Recurse -Force
    # Rebase only the official package locator; example assets remain relative.
    $Base = [System.IO.Path]::GetFullPath($ExDest).TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    $Utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
    Get-ChildItem -Path $ExDest -Filter xu.xun -File -Recurse | ForEach-Object {
        $Depth = ($_.FullName.Substring($Base.Length) -split '[\\/]').Length
        $PackagePath = ('../' * $Depth) + 'packages'
        $Text = [System.IO.File]::ReadAllText($_.FullName)
        $Text = [regex]::Replace($Text, '(?m)^(\s*"?github\.com/xulang-org/packages"?\s*:\s*)file:[^\r\n]+', [System.Text.RegularExpressions.MatchEvaluator]{ param($Match) $Match.Groups[1].Value + 'file:' + $PackagePath })
        [System.IO.File]::WriteAllText($_.FullName, $Text, $Utf8)
    }
}

# Metadata
$MetaFiles = @("README.md", "LICENSE", "VERSION", "TARGET", "bundle.json", "env.ps1", "uninstall.ps1")
foreach ($meta in $MetaFiles) {
    if (Test-Path "$SourceDir\$meta") {
        Copy-Item -Path "$SourceDir\$meta" -Destination "$Prefix\$meta" -Force
    } elseif (Test-Path "$ScriptDir\$meta") {
        Copy-Item -Path "$ScriptDir\$meta" -Destination "$Prefix\$meta" -Force
    } elseif (Test-Path "$SourceDir\scripts\$meta") {
        Copy-Item -Path "$SourceDir\scripts\$meta" -Destination "$Prefix\$meta" -Force
    } elseif (Test-Path "$ScriptDir\scripts\$meta") {
        Copy-Item -Path "$ScriptDir\scripts\$meta" -Destination "$Prefix\$meta" -Force
    }
}

Write-Color "[OK] Core files installed to: $Prefix" -Color Green

# Install VS Code Extension if code command is available
if ($env:XU_SKIP_EDITOR_INSTALL -ne "1" -and (Get-Command "code" -ErrorAction SilentlyContinue) -and $VsixFile) {
    Write-Color "[INFO] Installing VS Code extension..." -Color Blue
    code --install-extension $VsixFile.FullName --force | Out-Null
    Write-Color "[OK] VS Code extension installed." -Color Green
}

# Configure Environment Variables
if (-not $NoModifyPath) {
    Write-Color "[INFO] Configuring Windows user environment variables..." -Color Blue

    [System.Environment]::SetEnvironmentVariable("XU_ROOT", $Prefix, [System.EnvironmentVariableTarget]::User)
    [System.Environment]::SetEnvironmentVariable("XU_STDLIB_ROOT", "$Prefix\src", [System.EnvironmentVariableTarget]::User)
    $PreviousXuPath = [System.Environment]::GetEnvironmentVariable("XUPATH", [System.EnvironmentVariableTarget]::User)
    $XuPathVal = (@("$Prefix\src", "$Prefix\packages") + @($PreviousXuPath -split ';' | Where-Object { $_ })) | Select-Object -Unique
    $XuPathVal = $XuPathVal -join ';'
    [System.Environment]::SetEnvironmentVariable("XUPATH", $XuPathVal, [System.EnvironmentVariableTarget]::User)

    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)
    $PathParts = if ($UserPath) { $UserPath -split ';' | Where-Object { $_ } } else { @() }
    if ($PathParts -notcontains "$Prefix\bin") {
        $NewPath = if ($UserPath) { "$Prefix\bin;$UserPath" } else { "$Prefix\bin" }
        [System.Environment]::SetEnvironmentVariable("Path", $NewPath, [System.EnvironmentVariableTarget]::User)
    }

    # Also set in current session
    $env:XU_ROOT = $Prefix
    $env:XU_STDLIB_ROOT = "$Prefix\src"
    $env:XUPATH = $XuPathVal
    $env:Path = "$Prefix\bin;" + $env:Path
    Write-Color "[OK] Updated XU_ROOT, XUPATH and PATH." -Color Green
}

Write-Color "`n🎉 Xu 跨平台开发环境（Windows）安装成功！`n" -Color Green
Write-Host @"
组件清单：
  • 核心编译器与工具链: $Prefix\bin (xu.exe, xu-doctor.exe, xu-fmt.exe, etc.)
  • 标准库源码 (src):   $Prefix\src
  • 外部驱动模块（选装）:    $Prefix\packages (redis, mysql, postgres, sqlite, etc.)
  • 原生 C 接口头文件:  $Prefix\include
  • VS Code 扩展:       $Prefix\editors\vscode
  • 官方实战示例:       $Prefix\examples

验证使用：
  1. 重启当前 PowerShell 终端或执行:
     . "$Prefix\env.ps1"

  2. 验证编译器版本:
     xu --version

  3. 运行官方示例:
     xu run "$Prefix\examples\01_hello\main.xu"

  4. 检查系统环境诊断:
     xu doctor
"@
& "$BinDest\xu.exe" --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Installed compiler failed its version check." }
} finally {
    if ($TempZip -and (Test-Path $TempZip)) { Remove-Item $TempZip -Force }
    if ($TempExtract -and (Test-Path $TempExtract)) { Remove-Item $TempExtract -Recurse -Force }
}
