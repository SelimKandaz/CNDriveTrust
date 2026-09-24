param([string]$Root = 'C:\CNDriveTrust\Central')
$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath (Join-Path $Root 'config\central.json') | ConvertFrom-Json
$env:PYTHONPATH = Join-Path $Root 'app'
& $config.python_path -m cndrivetrust.central.server --root $Root --bind $config.bind --port $config.port `
  --cert $config.certificate --key $config.private_key --token-file $config.token_file

