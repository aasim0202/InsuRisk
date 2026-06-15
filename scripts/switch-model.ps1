# Switch the Ollama model InsuRisk uses (Windows / PowerShell)
# Usage: .\scripts\switch-model.ps1 -Model llama3.2:3b
param(
    [Parameter(Mandatory = $true)]
    [string]$Model
)
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root "backend\.env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root "backend\.env.example") $envFile
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "==> Pulling $Model"
    ollama pull $Model
} else {
    Write-Host "    Ollama not found - install from https://ollama.com/download (skipping pull)"
}

$content = Get-Content $envFile
if ($content -match '^OLLAMA_MODEL=') {
    $content = $content -replace '^OLLAMA_MODEL=.*', "OLLAMA_MODEL=$Model"
} else {
    $content += "OLLAMA_MODEL=$Model"
}
Set-Content -Path $envFile -Value $content -Encoding utf8

Write-Host "==> OLLAMA_MODEL set to '$Model'. Restart the backend to apply."
Write-Host ""
Write-Host "Recommended models by RAM footprint:"
Write-Host "  mistral        ~4.1 GB   default, best quality on 8GB"
Write-Host "  llama3.2:3b    ~2.0 GB   lighter, strong JSON adherence"
Write-Host "  phi3:mini      ~2.3 GB   strong step-by-step reasoning"
Write-Host "  gemma2:2b      ~1.6 GB   lightest, for very constrained machines"
