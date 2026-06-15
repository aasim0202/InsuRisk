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

Write-Host "==> Ollama models (primary + lighter fallback)"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    foreach ($var in @('OLLAMA_MODEL', 'OLLAMA_FALLBACK_MODEL')) {
        $line = Select-String -Path backend\.env -Pattern "^$var=(.*)$" | Select-Object -First 1
        if ($line) {
            $m = ($line.Matches.Groups[1].Value -split '#')[0].Trim()
            if ($m) {
                Write-Host "    Pulling '$m' (this can take a few minutes the first time)"
                ollama pull $m
            }
        }
    }
} else {
    Write-Host "    Ollama not found. Install from https://ollama.com/download then run: ollama pull mistral"
    Write-Host "    (No local Ollama is fine - the app falls back to Ollama Cloud if OLLAMA_API_KEY is set.)"
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
