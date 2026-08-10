param(
    [switch]$SkipInstall,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "The project virtual environment was not found at $Python"
}

Push-Location $ProjectRoot
try {
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
    Pop-Location
}
