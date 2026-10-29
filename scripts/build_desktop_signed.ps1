# 桌面端签名构建（一条命令）—— 没有证书时会明确告诉你缺什么，不会假装签过
#
# 用法：
#   pwsh -NoProfile -File scripts/build_desktop_signed.ps1 -Pfx "C:\path\cert.pfx" -Password "***"
#   pwsh -NoProfile -File scripts/build_desktop_signed.ps1 -SelfSigned        # 本地自签名（仅验证管线）
#
# 说明：
# - 证书走 electron-builder 的 CSC_LINK / CSC_KEY_PASSWORD，不写进仓库、不打印口令；
# - 构建完用 Get-AuthenticodeSignature 逐个核对 Setup/Portable/主程序；
# - 自签名只能证明"签名管线通"，SmartScreen 仍会提示（信任需要 CA 证书）。
param(
  [string]$Pfx = "",
  [string]$Password = "",
  [switch]$SelfSigned
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $repo 'desktop'
Set-Location $desktop

function New-SelfSignedPfx {
  $dir = Join-Path $env:TEMP 'clawd-signing'
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $path = Join-Path $dir 'clawd-dev.pfx'
  $alphabet = ([char[]](48..57 + 65..90 + 97..122))
  $pwd = -join (1..32 | ForEach-Object { $alphabet[(Get-Random -Maximum $alphabet.Length)] })
  $secure = ConvertTo-SecureString -String $pwd -AsPlainText -Force
  $cert = New-SelfSignedCertificate -Type CodeSigningCert `
    -Subject 'CN=Clawd Code Dev (self-signed)' `
    -CertStoreLocation 'Cert:\CurrentUser\My' `
    -KeyExportPolicy Exportable -KeyUsage DigitalSignature -NotAfter (Get-Date).AddYears(1)
  Export-PfxCertificate -Cert $cert -FilePath $path -Password $secure | Out-Null
  return @{ Path = $path; Password = $pwd; Thumbprint = $cert.Thumbprint }
}

if ($SelfSigned) {
  Write-Output '生成自签名证书（仅验证签名管线）...'
  $tmp = New-SelfSignedPfx
  $Pfx = $tmp.Path
  $Password = $tmp.Password
  Write-Output "证书指纹: $($tmp.Thumbprint)"
}

if (-not $Pfx) {
  Write-Output '缺证书：请用 -Pfx <证书路径> -Password <口令>，或加 -SelfSigned 做管线验证。'
  Write-Output '（没有 CA 证书时，产物不会被系统信任，SmartScreen 会提示"未知发布者"——这是外部条件，不是代码问题。）'
  exit 2
}
if (-not (Test-Path $Pfx)) { Write-Output "证书文件不存在: $Pfx"; exit 2 }

$env:CSC_LINK = (Resolve-Path $Pfx).Path
$env:CSC_KEY_PASSWORD = $Password
$env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'

Write-Output '开始构建（带签名）...'
npx electron-builder --win nsis portable 2>&1 | Select-Object -Last 12 | ForEach-Object { Write-Output $_ }

$ver = (Get-Content (Join-Path $desktop 'package.json') -Raw | ConvertFrom-Json).version
Write-Output '--- 签名验证 ---'
foreach ($f in @("dist\Clawd Desktop Setup $ver.exe", "dist\ClawdDesktop-Portable-$ver.exe")) {
  if (Test-Path $f) {
    $sig = Get-AuthenticodeSignature $f
    Write-Output ("{0} | Status={1} | Signer={2}" -f (Split-Path $f -Leaf), $sig.Status, $sig.SignerCertificate.Subject)
  } else {
    Write-Output "MISSING: $f"
  }
}
Write-Output 'DONE'
