param(
    [switch]$SkipInstall,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$CloudConfig = Join-Path $ProjectRoot "cloud_config.json"
$GeneratedCloudConfig = $false

if (-not (Test-Path -LiteralPath $Python)) {
    throw "The project virtual environment was not found at $Python"
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $CloudConfig)) {
        $CloudUrl = $env:SUPABASE_URL
        $CloudKey = $env:SUPABASE_PUBLISHABLE_KEY
        if ([string]::IsNullOrWhiteSpace($CloudUrl) -and (Test-Path -LiteralPath ".env")) {
            foreach ($Line in Get-Content -LiteralPath ".env") {
                if ($Line -match '^SUPABASE_URL=(.*)$') { $CloudUrl = $Matches[1].Trim().Trim('"').Trim("'") }
                if ($Line -match '^SUPABASE_PUBLISHABLE_KEY=(.*)$') { $CloudKey = $Matches[1].Trim().Trim('"').Trim("'") }
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($CloudUrl) -or -not [string]::IsNullOrWhiteSpace($CloudKey)) {
            if ([string]::IsNullOrWhiteSpace($CloudUrl) -or [string]::IsNullOrWhiteSpace($CloudKey)) {
                throw "Cloud builds require both SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY."
            }
            $ConfigObject = @{
                supabase_url = $CloudUrl
                supabase_publishable_key = $CloudKey
            }
            [System.IO.File]::WriteAllText($CloudConfig, ($ConfigObject | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
            $GeneratedCloudConfig = $true
        }
    }
    if (-not $SkipInstall) {
        & $Python -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    }

    $PyInstallerArguments = @("-m", "PyInstaller", "--noconfirm")
    if ($Clean) { $PyInstallerArguments += "--clean" }
    $PyInstallerArguments += "Focus.spec"
    & $Python @PyInstallerArguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $PackageDirectory = Join-Path $ProjectRoot "dist\Focus"
    $Executable = Join-Path $PackageDirectory "Focus.exe"
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "The build completed without producing dist\Focus\Focus.exe"
    }

    $Archive = Join-Path $ProjectRoot "dist\Focus-Windows.zip"
    Compress-Archive -Path (Join-Path $PackageDirectory "*") -DestinationPath $Archive -Force
    $Hash = Get-FileHash -LiteralPath $Executable -Algorithm SHA256
    Write-Host "Built $Executable"
    Write-Host "Portable archive $Archive"
    Write-Host "SHA256 $($Hash.Hash)"
}
finally {
    if ($GeneratedCloudConfig) { Remove-Item -LiteralPath $CloudConfig -Force }
    Pop-Location
}
