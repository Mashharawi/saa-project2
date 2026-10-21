<#
  Demo of the serverless image pipeline. Run it from PowerShell:
      .\scripts\demo.ps1 -Photo "C:\Users\Mash\Pictures\YOUR-PHOTO.jpg"
  It pauses between acts, so you control the pace while recording.
#>
param(
    [Parameter(Mandatory = $true)][string]$Photo
)

$region     = "us-east-1"
$api        = "https://12fdcfthf4.execute-api.us-east-1.amazonaws.com/upload-url"
$cfDomain   = "dhw66nafoy9yb.cloudfront.net"
$stateMachine = "arn:aws:states:us-east-1:121312796739:stateMachine:image-pipeline"
$processed  = "saa-p2-processed-121312796739"

if (-not (Test-Path $Photo)) { Write-Host "Photo not found: $Photo" -ForegroundColor Red; exit 1 }

function Banner($text) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Wait-Seconds($n, $why) {
    for ($i = $n; $i -gt 0; $i--) {
        Write-Host -NoNewline ("`r{0} ... {1,2}s " -f $why, $i)
        Start-Sleep -Seconds 1
    }
    Write-Host ("`r{0} ... done    " -f $why)
}

function Show-Executions {
    aws stepfunctions list-executions --state-machine-arn $stateMachine --max-results 3 --region $region `
        --query "executions[].{name:name,status:status,started:startDate}" --output table
}

function Upload-WithPresignedUrl($file, $name) {
    $body = @{ fileName = $name; contentType = "image/jpeg" } | ConvertTo-Json -Compress
    $resp = Invoke-RestMethod -Method Post -Uri $api -ContentType "application/json" -Body $body
    Write-Host "Object key chosen by the server: $($resp.key)" -ForegroundColor Yellow
    Write-Host "URL valid for $($resp.expiresInSeconds) seconds. Uploading directly to S3..."
    Invoke-WebRequest -UseBasicParsing -Method Put -Uri $resp.uploadUrl -InFile $file -ContentType "image/jpeg" |
        Select-Object StatusCode | Format-Table
}

# ---------------------------------------------------------------- Act 1
Banner "ACT 1: upload a real photo with a pre-signed URL"
Read-Host "Press Enter to start"
Upload-WithPresignedUrl $Photo "demo-photo.jpg"

Banner "ACT 2: the pipeline runs on its own"
Wait-Seconds 20 "SQS -> Lambda -> Step Functions"
Show-Executions
Write-Host "Open the Step Functions console now to show the green execution graph." -ForegroundColor Yellow
Read-Host "Press Enter to continue"

Banner "ACT 3: results in the private bucket, served through CloudFront"
$latest = aws s3api list-objects-v2 --bucket $processed --prefix images/ --region $region `
    --query "sort_by(Contents,&LastModified)[-1].Key" --output text
$thumb = $latest -replace '^images/', 'thumbnails/'
Write-Host "Newest processed image : $latest"
Write-Host "Its thumbnail          : $thumb"
aws s3 ls "s3://$processed/$latest" --region $region
aws s3 ls "s3://$processed/$thumb" --region $region
$url = "https://$cfDomain/$latest"
Write-Host "Opening: $url" -ForegroundColor Yellow
Start-Process $url
Read-Host "Show the watermark in the browser, then press Enter"

Banner "ACT 4: security check, the bucket itself is closed"
curl.exe -sI "https://$processed.s3.amazonaws.com/$latest" | Select-Object -First 1
curl.exe -sI "https://$cfDomain/work/anything.jpg" | Select-Object -First 1
Read-Host "Press Enter to continue"

Banner "ACT 5: failure path, a file that is not an image"
$bad = Join-Path $env:TEMP "not-an-image.jpg"
"this is plain text pretending to be a photo" | Out-File -Encoding ascii $bad
Upload-WithPresignedUrl $bad "not-an-image.jpg"
Wait-Seconds 20 "Validate step rejects it"
Show-Executions
Write-Host "Show the red Validate box in the Step Functions console and the failure email." -ForegroundColor Yellow
Remove-Item $bad -ErrorAction SilentlyContinue

Banner "Demo finished"
