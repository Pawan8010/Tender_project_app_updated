Set-Location "$PSScriptRoot\frontend"
if (!(Test-Path "node_modules")) {
  npm install
}
$port = 5173
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
  $port = 5174
}
npm run dev -- --host 127.0.0.1 --port $port
