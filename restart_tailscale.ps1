$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Wait-ServiceStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [System.ServiceProcess.ServiceControllerStatus]$Status,

        [int]$TimeoutSeconds = 20
    )

    $service = Get-Service -Name $Name -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ($service.Status -ne $Status -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $service.Refresh()
    }

    return $service.Status -eq $Status
}

function Get-ServiceProcessId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $wmiService = Get-CimInstance -ClassName Win32_Service -Filter "Name='$Name'"
    return [int]$wmiService.ProcessId
}

if (-not (Test-IsAdmin)) {
    Write-Host "Requesting administrator permission to restart Tailscale..."
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`""
    )

    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs
    exit
}

$serviceName = "Tailscale"

Write-Host "Restarting Tailscale service..."
Get-Service -Name $serviceName -ErrorAction Stop | Out-Null

$servicePid = Get-ServiceProcessId -Name $serviceName

try {
    Stop-Service -Name $serviceName -Force -ErrorAction Stop
} catch {
    Write-Host "Normal stop failed: $($_.Exception.Message)"
}

if (-not (Wait-ServiceStatus -Name $serviceName -Status Stopped -TimeoutSeconds 15)) {
    $servicePid = Get-ServiceProcessId -Name $serviceName

    if ($servicePid -gt 0) {
        Write-Host "Service did not stop cleanly. Killing Tailscale service process $servicePid..."
        Stop-Process -Id $servicePid -Force -ErrorAction Stop
        Wait-ServiceStatus -Name $serviceName -Status Stopped -TimeoutSeconds 10 | Out-Null
    }
}

Start-Service -Name $serviceName -ErrorAction Stop

if (-not (Wait-ServiceStatus -Name $serviceName -Status Running -TimeoutSeconds 20)) {
    throw "Tailscale service did not reach Running state."
}

Write-Host ""
Write-Host "Tailscale service is running."
Write-Host ""

if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    tailscale status
} else {
    Write-Host "tailscale.exe was not found on PATH, so status could not be printed."
}
