# InsuRisk one-shot setup (Windows / PowerShell)
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "==> Creating Python virtual environment (.venv)"
python -m venv .venv
& .\.venv\Scripts\Activate.ps1

Write-Host "==> Installing backend dependencies"
python -m pip install --upgrade pip | Out-Null
pip install -r backend\requirements.txt

Write-Host "==> Preparing environment file"
if (-not (Test-Path backend\.env)) {
    Copy-Item backend\.env.example backend\.env
    Write-Host "    Created backend\.env - open it and fill in TAVILY_API_KEY (and AWS keys if using S3)."
} else {
    Write-Host "    backend\.env already exists - leaving it untouched."
}

Write-Host "==> Ollama model"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $line = Select-String -Path backend\.env -Pattern '^OLLAMA_MODEL=(.*)$' | Select-Object -First 1
    $model = if ($line) { $line.Matches.Groups[1].Value } else { "mistral" }
    if (-not $model) { $model = "mistral" }
    Write-Host "    Pulling '$model' (this can take a few minutes the first time)"
    ollama pull $model
} else {
    Write-Host "    Ollama not found. Install from https://ollama.com/download then run: ollama pull mistral"
}

Write-Host ""
Write-Host "==> Setup complete."
Write-Host ""
Write-Host "Start the backend:"
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    cd backend"
Write-Host "    uvicorn main:app --reload --port 8000"
Write-Host ""
Write-Host "Then open frontend\index.html in your browser."
