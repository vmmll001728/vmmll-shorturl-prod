$ErrorActionPreference = "Continue"
$ProjectDir = "D:\智能\QClaw专区\projects\shorturl"
Set-Location $ProjectDir

Write-Host "Installing dependencies..."
pip install -r requirements.txt -q 2>&1 | Out-Null

Write-Host "Installing pytest-benchmark..."
pip install pytest-benchmark -q 2>&1 | Out-Null

Write-Host "Running tests with coverage..."
pytest tests/ -v --cov=app --cov-report=term 2>&1 | Tee-Object -Variable output

Write-Host "Test run complete."
Write-Host $output