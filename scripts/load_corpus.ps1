# Story 2.2: load sections, chunks, embeddings and the vector index into Atlas.
# First full run takes about 40 minutes (Voyage free-tier rate limit); re-runs resume.
# Usage: .\scripts\load_corpus.ps1 [-BatchSize 8] [-Delay 20] [-NoEmbed]
param([int]$BatchSize = 8, [double]$Delay = 20, [switch]$NoEmbed)
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .env)) { Write-Error ".env not found. Copy .env.example to .env and fill MONGODB_URI and VOYAGE_API_KEY."; exit 1 }
$uv = if (Get-Command uv -ErrorAction SilentlyContinue) { @("uv") } else { @("python", "-m", "uv") }
$extra = @("--batch-size", $BatchSize, "--delay", $Delay)
if ($NoEmbed) { $extra += "--no-embed" }
& $uv[0] $uv[1..($uv.Count)] run python -m building_with_rag.load_corpus @extra
exit $LASTEXITCODE
