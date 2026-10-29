param([Parameter(Mandatory = $true)][string]$ResultsDirectory)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$logs = @(Get-ChildItem -LiteralPath $ResultsDirectory -Recurse -Filter '*chrome.log' -File)
if (-not $logs) { throw 'No real Chrome startup logs were retained' }
$failures = @($logs | Select-String -Pattern 'Sandbox cannot access executable')
if ($failures) {
    $failures | ForEach-Object { Write-Output $_.ToString() }
    throw 'Chrome sandbox could not read its executable; preserve the logs and staging receipt'
}
Write-Output "Checked $($logs.Count) real Chrome startup logs; executable access was not refused."
