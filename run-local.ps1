param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
$backendDirectory = Join-Path $PSScriptRoot 'backend'
$pythonExecutable = Join-Path $backendDirectory 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create backend\venv and install backend\requirements.txt first.'
}

$localTools = Join-Path $PSScriptRoot '.local-tools'
$ffmpegExecutable = Get-ChildItem (Join-Path $localTools 'ffmpeg') -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ffmpegExecutable) {
    $env:PATH = $ffmpegExecutable.DirectoryName + ';' + $env:PATH
}
$denoDirectory = Join-Path $localTools 'deno'
if (Test-Path (Join-Path $denoDirectory 'deno.exe')) {
    $env:PATH = $denoDirectory + ';' + $env:PATH
}
if (-not $env:STEPSYNC_DATA_DIRECTORY) {
    $env:STEPSYNC_DATA_DIRECTORY = Join-Path $localTools 'data'
}

Push-Location $backendDirectory
try {
    & $pythonExecutable -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
