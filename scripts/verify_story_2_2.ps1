# Story 2.2 checks: section-to-chunk link, embedding dimension, index readiness, sample $vectorSearch.
# Usage: .\scripts\verify_story_2_2.ps1 [-Section bns:103] [-Question "punishment for theft"]
param([string]$Section = "bns:103", [string]$Question = "punishment for theft")
Set-Location (Split-Path $PSScriptRoot -Parent)
$uv = if (Get-Command uv -ErrorAction SilentlyContinue) { @("uv") } else { @("python", "-m", "uv") }
& $uv[0] $uv[1..($uv.Count)] run python -m building_with_rag.verify_corpus --section $Section --question $Question
exit $LASTEXITCODE
