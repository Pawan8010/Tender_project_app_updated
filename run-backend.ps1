$backendPath = Join-Path $PSScriptRoot "backend"
Set-Location $backendPath

if (!(Test-Path ".env")) {
  Copy-Item ".env.demo" ".env"
  $secret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
  (Get-Content ".env") `
    -replace "SECRET_KEY=local-demo-secret-change-before-production", "SECRET_KEY=$secret" `
    -replace "JWT_SECRET=local-demo-secret-change-before-production", "JWT_SECRET=$secret" |
    Set-Content ".env"
}

if (!(Test-Path "data")) {
  New-Item -ItemType Directory -Path "data" | Out-Null
}

if (!(Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
}

.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
