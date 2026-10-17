# Xu Programming Language — Windows Development Environment Installer
# Supports offline installation (from unpacked bundle) and online installation (irm | iex).

[CmdletBinding()]
param (
    [string]$Prefix = $(if ($env:XU_INSTALL_DIR) { $env:XU_INSTALL_DIR } else { "$HOME\.xu" }),
    [string]$Version = $(if ($env:XU_VERSION) { $env:XU_VERSION } else { "" }),
    [switch]$NoModifyPath = $(if ($env:XU_NO_MODIFY_PATH -eq "1") { $true } else { $false }),
    [switch]$Online = $false
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

if ($Arch -notin @("x64", "arm64")) {
    throw "Unsupported Windows architecture: $Arch (Xu currently supports x64 and arm64 on Windows)"
}
$Platform = "windows-$Arch"
$Prefix = [System.IO.Path]::GetFullPath($Prefix)

Write-Color "[INFO] Detected Windows Architecture: $Arch ($Platform)" -Color Blue
Write-Color "[INFO] Target Install Directory: $Prefix" -Color Blue

# Check whether running from a physical local script file or via pipeline (irm | iex)
$IsLocalScript = $false
$ScriptDir = $null
if (-not $Online -and $PSScriptRoot -and (Test-Path -Path $PSScriptRoot -PathType Container)) {
    try {
        $InvokedPath = $MyInvocation.MyCommand.Path
        if ($InvokedPath -and (Test-Path -Path $InvokedPath -PathType Leaf)) {
            $IsLocalScript = $true
            $ScriptDir = $PSScriptRoot
        }
    } catch {}
}

$SourceDir = $null
# Only check local candidates if truly invoked from a physical script file
if ($IsLocalScript -and $ScriptDir) {
    foreach ($Candidate in @($ScriptDir, (Resolve-Path "$ScriptDir\..").Path)) {
        if ($Candidate -and (Test-Path "$Candidate\src" -PathType Container)) {
            if ((Test-Path "$Candidate\VERSION" -PathType Leaf) -or (Test-Path "$Candidate\TARGET" -PathType Leaf) -or (Test-Path "$Candidate\bin" -PathType Container)) {
                $SourceDir = $Candidate
                Write-Color "[INFO] Found local offline distribution files in: $SourceDir" -Color Blue
                break
            }
        }
    }
}

# Resolve version
$FallbackVersion = "0.8.12"
if (-not $Version) {
    if ($SourceDir -and (Test-Path "$SourceDir\VERSION")) {
        $Version = (Get-Content "$SourceDir\VERSION" -Raw).Trim()
    } else {
        # Try querying latest official release with a short timeout
        try {
            $headers = @{ "User-Agent" = "xu-installer" }
            $latest = Invoke-RestMethod -Uri "https://api.github.com/repos/xulang-org/xu/releases/latest" -Headers $headers -TimeoutSec 2 -ErrorAction SilentlyContinue -UseBasicParsing
            if ($latest.tag_name -match '^v?(\d+\.\d+\.\d+)') {
                $Version = $Matches[1]
                Write-Color "[INFO] Resolved latest release version: v$Version" -Color Blue
            }
        } catch {}
        if (-not $Version) {
            $Version = $FallbackVersion
        }
    }
}

$TempZip = $null
$TempExtract = $null
try {
    if (-not $SourceDir) {
        $DownloadBase = if ($env:XU_DOWNLOAD_URL) { $env:XU_DOWNLOAD_URL.TrimEnd('/') } else { "https://github.com/xulang-org/xu/releases/download" }
        $ArchiveName = "xu-v$Version-$Platform.zip"
        $DownloadUrl = "$DownloadBase/v$Version/$ArchiveName"
        $TempZip = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "xu_install_" + [System.Guid]::NewGuid().ToString() + ".zip")
        $TempExtract = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "xu_install_" + [System.Guid]::NewGuid().ToString())

        Write-Color "[INFO] Preparing to download online release v$Version for $Platform..." -Color Blue
        Write-Color "[INFO] Downloading $DownloadUrl..." -Color Blue
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $TempZip -UseBasicParsing

        Write-Color "[INFO] Extracting bundle..." -Color Blue
        Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force

        # Intelligent root discovery
        if ((Test-Path "$TempExtract\src" -PathType Container) -and (Test-Path "$TempExtract\VERSION" -PathType Leaf)) {
            $SourceDir = $TempExtract
        } else {
            foreach ($Sub in (Get-ChildItem $TempExtract -Directory)) {
                if ((Test-Path "$($Sub.FullName)\src" -PathType Container) -and (Test-Path "$($Sub.FullName)\VERSION" -PathType Leaf)) {
                    $SourceDir = $Sub.FullName
                    break
                }
            }
            if (-not $SourceDir) {
                $FoundSrc = Get-ChildItem -Path $TempExtract -Filter "src" -Directory -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($FoundSrc) {
                    $SourceDir = $FoundSrc.Parent.FullName
                }
            }
        }

        if (-not $SourceDir -or -not (Test-Path $SourceDir)) {
            throw "Failed to locate extracted distribution files in $TempExtract."
        }
    }

    # Pre-flight validation
    if (-not (Test-Path "$SourceDir\src" -PathType Container) -or -not (Test-Path "$SourceDir\VERSION" -PathType Leaf)) {
        throw "Invalid Xu distribution: src/ or VERSION missing in $SourceDir."
    }
    if (Test-Path "$SourceDir\TARGET") {
        $BundleTarget = (Get-Content "$SourceDir\TARGET" -Raw).Trim()
        if ($BundleTarget -ne $Platform -and $BundleTarget -ne "devkit-all") {
            throw "Bundle target '$BundleTarget' does not match host '$Platform'."
        }
    }
    $BinarySource = "$SourceDir\bin"
    if (Test-Path "$BinarySource\platform\$Platform") {
        $BinarySource = "$BinarySource\platform\$Platform"
    }
    if (-not (Test-Path "$BinarySource\xu.exe" -PathType Leaf)) {
        throw "Distribution compiler missing: $BinarySource\xu.exe"
    }
    & "$BinarySource\xu.exe" --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Distribution compiler cannot run on $Platform."
    }
    if ($Prefix -eq (Resolve-Path $SourceDir).Path) {
        throw "Install directory must differ from source distribution. Use . .\env.ps1 to activate in place."
    }

    if (-not (Test-Path $Prefix)) {
        New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
    }

    # 1. Toolchain binaries
    Write-Color "[INFO] Copying toolchain binaries..." -Color Blue
    $BinDest = "$Prefix\bin"
    if (-not (Test-Path $BinDest)) { New-Item -ItemType Directory -Path $BinDest -Force | Out-Null }
    if (Test-Path "$SourceDir\bin\platform\$Platform") {
        Copy-Item -Path "$SourceDir\bin\platform\$Platform\*" -Destination $BinDest -Recurse -Force
    } elseif (Test-Path "$SourceDir\bin") {
        $Tools = @("xu", "xu-doctor", "xu-fmt", "xu-doc", "xu-map", "xu-desktop", "xu-native", "xu-setup")
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

    # 3. External modules (packages/)
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

    # 4. Native C headers (include/)
    if (Test-Path "$SourceDir\include") {
        Write-Color "[INFO] Copying native headers (include/)..." -Color Blue
        $IncDest = "$Prefix\include"
        if (Test-Path $IncDest) { Remove-Item -Path $IncDest -Recurse -Force }
        Copy-Item -Path "$SourceDir\include" -Destination $Prefix -Recurse -Force
    }

    # 5. VS Code extension (editors/vscode)
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
    if ($VscodeSource -and (Test-Path "$VscodeSource\package.json")) {
        try {
            $Extension = Get-Content "$VscodeSource\package.json" -Raw | ConvertFrom-Json
            if ($Extension.name -match '^[A-Za-z0-9_-]+$' -and $Extension.version -match '^\d+\.\d+\.\d+') {
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
            }
        } catch {}
    } else {
        Write-Color "[INFO] VS Code extension repository absent; core toolchain installed." -Color Blue
    }

    # 6. Official examples (examples/)
    $ExSrc = "$SourceDir\examples"
    if (-not (Test-Path $ExSrc) -and $env:XU_EXAMPLES_ROOT) { $ExSrc = "$env:XU_EXAMPLES_ROOT\examples" }
    if (Test-Path $ExSrc) {
        Write-Color "[INFO] Copying official examples..." -Color Blue
        $ExDest = "$Prefix\examples"
        if (Test-Path $ExDest) { Remove-Item -Path $ExDest -Recurse -Force }
        Copy-Item -Path $ExSrc -Destination $ExDest -Recurse -Force
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

    # 7. Metadata
    $MetaFiles = @("README.md", "LICENSE", "VERSION", "TARGET", "bundle.json", "env.ps1", "uninstall.ps1")
    foreach ($meta in $MetaFiles) {
        if (Test-Path "$SourceDir\$meta") {
            Copy-Item -Path "$SourceDir\$meta" -Destination "$Prefix\$meta" -Force
        } elseif ($ScriptDir -and (Test-Path "$ScriptDir\$meta")) {
            Copy-Item -Path "$ScriptDir\$meta" -Destination "$Prefix\$meta" -Force
        } elseif (Test-Path "$SourceDir\scripts\$meta") {
            Copy-Item -Path "$SourceDir\scripts\$meta" -Destination "$Prefix\$meta" -Force
        } elseif ($ScriptDir -and (Test-Path "$ScriptDir\scripts\$meta")) {
            Copy-Item -Path "$ScriptDir\scripts\$meta" -Destination "$Prefix\$meta" -Force
        }
    }

    # Ensure env.ps1 ALWAYS exists
    $EnvScriptPath = "$Prefix\env.ps1"
    $EnvScriptContent = @"
# Xu Development Environment Activation Script
`$XuEnvDir = `$null
try {
    if (`$MyInvocation.MyCommand.Path) {
        `$XuEnvDir = Split-Path -Parent `$MyInvocation.MyCommand.Path
    }
} catch {}
if (-not `$XuEnvDir -or -not (Test-Path "`$XuEnvDir\src")) {
    `$XuEnvDir = "$Prefix"
}
`$env:XU_ROOT = `$XuEnvDir
`$env:XU_STDLIB_ROOT = "`$XuEnvDir\src"
`$XuEnvBin = "`$XuEnvDir\bin"
`$XuEnvArch = `$null
try {
    `$osArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    if (`$null -ne `$osArch) { `$XuEnvArch = `$osArch.ToString().ToLowerInvariant() }
} catch {}
if (-not `$XuEnvArch) {
    `$rawArch = if (`$env:PROCESSOR_ARCHITEW6432) { `$env:PROCESSOR_ARCHITEW6432 } else { `$env:PROCESSOR_ARCHITECTURE }
    if (`$rawArch -match "ARM64") { `$XuEnvArch = "arm64" } else { `$XuEnvArch = "x64" }
}
if (Test-Path "`$XuEnvBin\platform\windows-`$XuEnvArch") {
    `$XuEnvBin = "`$XuEnvBin\platform\windows-`$XuEnvArch"
}
foreach (`$XuEnvPath in @("`$XuEnvDir\packages", "`$XuEnvDir\src")) {
    if ((Test-Path `$XuEnvPath) -and ((`$env:XUPATH -split ';') -notcontains `$XuEnvPath)) {
        `$env:XUPATH = (@(`$XuEnvPath) + @(`$env:XUPATH -split ';' | Where-Object { `$_ })) -join ';'
    }
}
if ((`$env:Path -split ';') -notcontains `$XuEnvBin) {
    `$env:Path = "`$XuEnvBin;" + `$env:Path
}
Write-Host "Xu environment activated: `$XuEnvDir" -ForegroundColor Green
"@
    [System.IO.File]::WriteAllText($EnvScriptPath, $EnvScriptContent, [System.Text.Encoding]::UTF8)

    # Ensure uninstall.ps1 ALWAYS exists
    $UninstallScriptPath = "$Prefix\uninstall.ps1"
    $UninstallScriptContent = @"
# Xu Programming Language — Windows Uninstaller
param (
    [string]`$TargetPrefix = "$Prefix"
)
Write-Host "Removing Xu Development Environment from: `$TargetPrefix" -ForegroundColor Yellow
if (Test-Path `$TargetPrefix) {
    Remove-Item -Path `$TargetPrefix -Recurse -Force
    Write-Host "[OK] Removed `$TargetPrefix" -ForegroundColor Green
}
[System.Environment]::SetEnvironmentVariable("XU_ROOT", `$null, [System.EnvironmentVariableTarget]::User)
[System.Environment]::SetEnvironmentVariable("XU_STDLIB_ROOT", `$null, [System.EnvironmentVariableTarget]::User)
[System.Environment]::SetEnvironmentVariable("XUPATH", `$null, [System.EnvironmentVariableTarget]::User)
`$UserPath = [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)
if (`$UserPath -like "*`$TargetPrefix\bin*") {
    `$CleanPath = (`$UserPath -split ";" | Where-Object { `$_ -ne "`$TargetPrefix\bin" -and `$_ -ne "" }) -join ";"
    [System.Environment]::SetEnvironmentVariable("Path", `$CleanPath, [System.EnvironmentVariableTarget]::User)
    Write-Host "[OK] Removed from User PATH" -ForegroundColor Green
}
Write-Host "Xu has been uninstalled successfully." -ForegroundColor Green
"@
    [System.IO.File]::WriteAllText($UninstallScriptPath, $UninstallScriptContent, [System.Text.Encoding]::UTF8)

    Write-Color "[OK] Core development files installed to: $Prefix" -Color Green

    # Install VS Code Extension if code command is available
    if ($env:XU_SKIP_EDITOR_INSTALL -ne "1" -and (Get-Command "code" -ErrorAction SilentlyContinue) -and $VsixFile) {
        Write-Color "[INFO] Detected VS Code CLI. Installing Xu Language extension..." -Color Blue
        try {
            code --install-extension $VsixFile.FullName --force | Out-Null
            Write-Color "[OK] VS Code extension installed." -Color Green
        } catch {
            Write-Color "[WARN] Failed to install VS Code extension automatically." -Color Yellow
        }
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

    Write-Color "`n🎉 Xu development environment (Windows) installed successfully!`n" -Color Green
    Write-Host @"
Installed components:
  • Core compiler & toolchain: $Prefix\bin (xu.exe, xu-doctor.exe, xu-fmt.exe, etc.)
  • Standard library (src):    $Prefix\src
  • External driver modules:   $Prefix\packages (redis, mysql, postgres, sqlite, etc.)
  • Native C headers:          $Prefix\include
  • VS Code extension:         $Prefix\editors\vscode
  • Official examples:         $Prefix\examples

To get started:
  1. Restart PowerShell or activate in current session:
     . "$Prefix\env.ps1"

  2. Verify compiler version:
     xu --version

  3. Compile and run an official example:
     xu run "$Prefix\examples\01_hello\main.xu"

  4. Check toolchain diagnosis:
     xu doctor
"@

    # Self-check compiler
    & "$BinDest\xu.exe" --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Installed compiler failed its version check."
    }

} finally {
    if ($TempZip -and (Test-Path $TempZip)) {
        Remove-Item $TempZip -Force -ErrorAction SilentlyContinue
    }
    if ($TempExtract -and (Test-Path $TempExtract)) {
        Remove-Item $TempExtract -Recurse -Force -ErrorAction SilentlyContinue
    }
}
