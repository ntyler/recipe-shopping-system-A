#requires -Version 5.1
<#
.SYNOPSIS
Synchronizes local Selenium ChromeDriver and EdgeDriver binaries with installed browsers.

.DESCRIPTION
Chrome and Edge can auto-update faster than the driver binaries on PATH. This script
detects the installed browser versions, downloads the matching Windows WebDriver zip,
backs up the old driver binary, and replaces it in the target driver directory.

ChromeDriver 115+ is resolved through the Chrome for Testing JSON endpoints.
EdgeDriver is resolved from Microsoft's official Edge WebDriver CDN using the
installed Edge build.

.EXAMPLE
.\scripts\sync_webdrivers.ps1

.EXAMPLE
.\scripts\sync_webdrivers.ps1 -PlanOnly

.EXAMPLE
.\scripts\sync_webdrivers.ps1 -ChromeOnly -DriverDir C:\Python39Drivers

.EXAMPLE
.\scripts\sync_webdrivers.ps1 -UpdateBrowsers
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DriverDir = "",
    [switch]$ChromeOnly,
    [switch]$EdgeOnly,
    [switch]$UpdateBrowsers,
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ChromeLatestPatchEndpoint = "https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build-with-downloads.json"
$ChromeKnownGoodEndpoint = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Get-ExistingCommandDir {
    param([string]$ExeName)

    $command = Get-Command $ExeName -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command -and $command.Source) {
        return (Split-Path -Parent $command.Source)
    }

    return ""
}

function Resolve-DriverDirectory {
    param([string]$RequestedDir)

    if ($RequestedDir.Trim()) {
        return [System.IO.Path]::GetFullPath($RequestedDir)
    }

    $existingDir = Get-ExistingCommandDir "chromedriver.exe"
    if (-not $existingDir) {
        $existingDir = Get-ExistingCommandDir "msedgedriver.exe"
    }
    if ($existingDir) {
        return $existingDir
    }

    return "C:\Python39Drivers"
}

function Get-WindowsDriverPlatform {
    if ([Environment]::Is64BitOperatingSystem) {
        return "win64"
    }

    return "win32"
}

function Get-FileProductVersion {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if (-not $candidate) {
            continue
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }

        $versionInfo = (Get-Item -LiteralPath $candidate).VersionInfo
        $versionText = $versionInfo.ProductVersion
        if (-not $versionText) {
            $versionText = $versionInfo.FileVersion
        }
        if ($versionText -match "\d+\.\d+\.\d+\.\d+") {
            return [pscustomobject]@{
                Path = $candidate
                Version = $Matches[0]
            }
        }
    }

    return $null
}

function Get-ChromeInstall {
    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    $programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")

    return Get-FileProductVersion @(
        (Join-Path $programFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path $programFilesX86 "Google\Chrome\Application\chrome.exe"),
        (Join-Path $localAppData "Google\Chrome\Application\chrome.exe")
    )
}

function Get-EdgeInstall {
    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    $programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")

    return Get-FileProductVersion @(
        (Join-Path $programFilesX86 "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $programFiles "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $localAppData "Microsoft\Edge\Application\msedge.exe")
    )
}

function Get-DriverVersion {
    param([string]$DriverPath)

    if (-not (Test-Path -LiteralPath $DriverPath -PathType Leaf)) {
        return ""
    }

    $output = & $DriverPath --version 2>$null
    if ($output -match "\d+\.\d+\.\d+\.\d+") {
        return $Matches[0]
    }

    return ""
}

function Invoke-JsonRequest {
    param([string]$Url)

    return Invoke-RestMethod `
        -Uri $Url `
        -Headers @{ "User-Agent" = "recipe-shopping-system-webdriver-sync" } `
        -UseBasicParsing
}

function Get-ChromeDriverDownload {
    param(
        [object]$VersionEntry,
        [string]$Platform
    )

    $downloadsProperty = $VersionEntry.downloads.PSObject.Properties["chromedriver"]
    if (-not $downloadsProperty) {
        return $null
    }

    $download = @($downloadsProperty.Value) |
        Where-Object { $_.platform -eq $Platform } |
        Select-Object -First 1

    if (-not $download) {
        return $null
    }

    return [pscustomobject]@{
        Browser = "Chrome"
        DriverName = "ChromeDriver"
        ExeName = "chromedriver.exe"
        BrowserVersion = ""
        DriverVersion = $VersionEntry.version
        Url = $download.url
        Platform = $Platform
    }
}

function Resolve-ChromeDriver {
    param(
        [string]$BrowserVersion,
        [string]$Platform
    )

    $parts = $BrowserVersion.Split(".")
    $major = [int]$parts[0]

    if ($major -lt 115) {
        throw "ChromeDriver auto-sync supports Chrome 115+. Detected Chrome $BrowserVersion."
    }

    $buildKey = "$($parts[0]).$($parts[1]).$($parts[2])"
    $patches = Invoke-JsonRequest $ChromeLatestPatchEndpoint
    $buildProperty = $patches.builds.PSObject.Properties[$buildKey]

    if ($buildProperty) {
        $download = Get-ChromeDriverDownload $buildProperty.Value $Platform
        if ($download) {
            $download.BrowserVersion = $BrowserVersion
            return $download
        }
    }

    $knownGood = Invoke-JsonRequest $ChromeKnownGoodEndpoint
    $fallback = @($knownGood.versions) |
        Where-Object {
            $_.version -like "$major.*" -and $_.downloads.PSObject.Properties["chromedriver"]
        } |
        Sort-Object { [version]$_.version } -Descending |
        Select-Object -First 1

    if (-not $fallback) {
        throw "Could not find a ChromeDriver download for Chrome $BrowserVersion."
    }

    $download = Get-ChromeDriverDownload $fallback $Platform
    if (-not $download) {
        throw "Could not find a ChromeDriver $Platform download for Chrome $BrowserVersion."
    }

    $download.BrowserVersion = $BrowserVersion
    return $download
}

function Resolve-EdgeDriver {
    param(
        [string]$BrowserVersion,
        [string]$Platform
    )

    return [pscustomobject]@{
        Browser = "Edge"
        DriverName = "EdgeDriver"
        ExeName = "msedgedriver.exe"
        BrowserVersion = $BrowserVersion
        DriverVersion = $BrowserVersion
        Url = "https://msedgedriver.microsoft.com/$BrowserVersion/edgedriver_$Platform.zip"
        Platform = $Platform
    }
}

function Remove-TemporaryDirectory {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return
    }

    $tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $leafName = Split-Path -Leaf $resolvedPath

    if (
        $resolvedPath.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -and
        $leafName.StartsWith("webdriver-sync-", [StringComparison]::OrdinalIgnoreCase)
    ) {
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
}

function Install-WebDriver {
    param(
        [object]$Driver,
        [string]$TargetDir,
        [switch]$Plan
    )

    $destination = Join-Path $TargetDir $Driver.ExeName
    $currentVersion = Get-DriverVersion $destination

    Write-Step "$($Driver.DriverName): browser $($Driver.BrowserVersion), target driver $($Driver.DriverVersion)"
    if ($currentVersion) {
        Write-Host "Current $($Driver.ExeName): $currentVersion at $destination"
    }
    else {
        Write-Host "Current $($Driver.ExeName): not found at $destination"
    }

    if ($currentVersion -eq $Driver.DriverVersion) {
        Write-Host "$($Driver.DriverName) is already in sync."
        return
    }

    if ($Plan) {
        Write-Host "Plan: download $($Driver.Url)"
        Write-Host "Plan: install to $destination"
        return
    }

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "webdriver-sync-$([guid]::NewGuid().ToString("N"))"

    try {
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        $zipPath = Join-Path $tempRoot "$($Driver.Browser)-webdriver.zip"
        $extractPath = Join-Path $tempRoot "extract"

        if ($PSCmdlet.ShouldProcess($Driver.Url, "Download $($Driver.DriverName)")) {
            Invoke-WebRequest `
                -Uri $Driver.Url `
                -OutFile $zipPath `
                -Headers @{ "User-Agent" = "recipe-shopping-system-webdriver-sync" } `
                -UseBasicParsing
        }

        if ($PSCmdlet.ShouldProcess($zipPath, "Extract $($Driver.DriverName)")) {
            Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force
        }

        $extractedDriver = Get-ChildItem -LiteralPath $extractPath -Recurse -Filter $Driver.ExeName |
            Select-Object -First 1
        if (-not $extractedDriver) {
            throw "Downloaded archive did not contain $($Driver.ExeName)."
        }

        if (-not (Test-Path -LiteralPath $TargetDir)) {
            New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
        }

        if ((Test-Path -LiteralPath $destination -PathType Leaf) -and $currentVersion) {
            $timestamp = Get-Date -Format "yyyyMMddHHmmss"
            $backupPath = "$destination.bak.$timestamp"
            if ($PSCmdlet.ShouldProcess($destination, "Back up existing driver to $backupPath")) {
                Copy-Item -LiteralPath $destination -Destination $backupPath -Force
                Write-Host "Backed up existing driver to $backupPath"
            }
        }

        if ($PSCmdlet.ShouldProcess($destination, "Install $($Driver.DriverName) $($Driver.DriverVersion)")) {
            Copy-Item -LiteralPath $extractedDriver.FullName -Destination $destination -Force
            Unblock-File -LiteralPath $destination -ErrorAction SilentlyContinue
            Write-Host "Installed $($Driver.DriverName) $($Driver.DriverVersion) to $destination"
        }
    }
    finally {
        Remove-TemporaryDirectory $tempRoot
    }
}

function Invoke-BrowserUpdates {
    param([switch]$Plan)

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        Write-Warning "winget.exe was not found. Skipping browser update check."
        return
    }

    $packages = @(
        [pscustomobject]@{ Name = "Google Chrome"; Id = "Google.Chrome" },
        [pscustomobject]@{ Name = "Microsoft Edge"; Id = "Microsoft.Edge" }
    )

    foreach ($package in $packages) {
        if ($Plan) {
            Write-Host "Plan: winget upgrade --id $($package.Id) --silent"
            continue
        }

        if ($PSCmdlet.ShouldProcess($package.Name, "Check/install browser update with winget")) {
            & $winget.Source upgrade `
                --id $package.Id `
                --silent `
                --accept-package-agreements `
                --accept-source-agreements

            if ($LASTEXITCODE -ne 0) {
                Write-Warning "winget exited with code $LASTEXITCODE while updating $($package.Name). If no update was available, this can be harmless."
            }
        }
    }
}

if ($ChromeOnly -and $EdgeOnly) {
    throw "Use either -ChromeOnly or -EdgeOnly, not both."
}

$syncChrome = -not $EdgeOnly
$syncEdge = -not $ChromeOnly
$targetDriverDir = Resolve-DriverDirectory $DriverDir
$platform = Get-WindowsDriverPlatform

Write-Step "Target driver directory: $targetDriverDir"
Write-Host "Windows driver platform: $platform"

if ($UpdateBrowsers) {
    Invoke-BrowserUpdates -Plan:$PlanOnly
}

if ($syncChrome) {
    $chrome = Get-ChromeInstall
    if ($chrome) {
        Write-Host "Detected Chrome $($chrome.Version) at $($chrome.Path)"
        $driver = Resolve-ChromeDriver $chrome.Version $platform
        Install-WebDriver $driver $targetDriverDir -Plan:$PlanOnly
    }
    else {
        Write-Warning "Google Chrome was not found."
    }
}

if ($syncEdge) {
    $edge = Get-EdgeInstall
    if ($edge) {
        Write-Host "Detected Edge $($edge.Version) at $($edge.Path)"
        $driver = Resolve-EdgeDriver $edge.Version $platform
        Install-WebDriver $driver $targetDriverDir -Plan:$PlanOnly
    }
    else {
        Write-Warning "Microsoft Edge was not found."
    }
}

Write-Step "WebDriver sync finished."
