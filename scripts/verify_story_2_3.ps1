# Story 2.3 checks (compact output only). Usage: .\scripts\verify_story_2_3.ps1 [-Question "..."] [-NoQuery]
param([string]$Question = "What is the punishment for theft?", [switch]$NoQuery)
Set-Location (Split-Path $PSScriptRoot -Parent)
$uv = if (Get-Command uv -ErrorAction SilentlyContinue) { @("uv") } else { @("python", "-m", "uv") }
$extra = @()
if ($NoQuery) { $extra += "--no-query" }
& $uv[0] $uv[1..($uv.Count)] run python -m building_with_rag.verify_semantic --question $Question @extra
exit $LASTEXITCODE
