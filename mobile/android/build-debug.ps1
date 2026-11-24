param(
    [string]$Sdk = "$env:LOCALAPPDATA\Android\Sdk",
    [string]$Jdk = "$env:ProgramFiles\Android\Android Studio\jbr",
    [string]$WorkDir = "$env:TEMP\campuscats-android-build",
    [string]$Keystore = "$env:LOCALAPPDATA\CampusCats\signing\campuscats-signing.jks",
    [string]$StorePass = 'android',
    [string]$KeyAlias = 'pilot',
    [string]$KeyPass = 'android',
    [string]$OutputApk = (Join-Path $PSScriptRoot '..\..\CampusCats-android-debug.apk'),
    [string]$SchoolOrigin = ''
)
$ErrorActionPreference = 'Stop'
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program exited with $LASTEXITCODE" }
}
$env:JAVA_HOME = $Jdk
$env:PATH = "$Jdk\bin;$env:PATH"
$toolsDir = Get-ChildItem (Join-Path $Sdk 'build-tools') -Directory |
    Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
$platformDir = Get-ChildItem (Join-Path $Sdk 'platforms') -Directory |
    Where-Object { $_.Name -match '^android-\d+$' } |
    Sort-Object { [int]($_.Name -replace 'android-','') } -Descending | Select-Object -First 1
if (!$toolsDir -or !$platformDir) { throw 'Install Android SDK Platform 35 or newer and matching Build Tools.' }
$bt = $toolsDir.FullName
$platform = Join-Path $platformDir.FullName 'android.jar'
$build = Join-Path $WorkDir ([guid]::NewGuid().ToString('N'))
$classes = Join-Path $build 'classes'
$dex = Join-Path $build 'dex'
New-Item -ItemType Directory -Force -Path $classes,$dex | Out-Null
$jar = Join-Path $build 'app.jar'
$unsigned = Join-Path $build 'unsigned.apk'
$aligned = Join-Path $build 'aligned.apk'
$key = $Keystore
$keyDir = Split-Path -Parent $key
if ($keyDir -and !(Test-Path -LiteralPath $keyDir)) {
    New-Item -ItemType Directory -Force -Path $keyDir | Out-Null
}
$sources = @(Get-ChildItem -Path (Join-Path $PSScriptRoot 'src\campus\cats\*.java') | ForEach-Object FullName)
$emptySources = Join-Path $build 'sourcepath'
New-Item -ItemType Directory -Path $emptySources | Out-Null
$compileArgs = @('-encoding','UTF-8','-Xlint:-options','-source','8','-target','8','-sourcepath',$emptySources,'-classpath',$platform,'-d',$classes) + $sources
Invoke-Checked "$Jdk\bin\javac.exe" $compileArgs
Invoke-Checked "$Jdk\bin\jar.exe" @('cf',$jar,'-C',$classes,'.')
Invoke-Checked "$bt\d8.bat" @('--min-api','26','--lib',$platform,'--output',$dex,$jar)
$res = Join-Path $PSScriptRoot 'res'
if ($SchoolOrigin) {
    $uri = [uri]$SchoolOrigin
    if (!$uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.PathAndQuery -ne '/' -or $uri.Fragment) {
        throw 'SchoolOrigin must be an HTTPS origin without a path, credentials or query.'
    }
    Copy-Item -LiteralPath $res -Destination (Join-Path $build 'res') -Recurse
    $res = Join-Path $build 'res'
    $configFile = Join-Path $res 'values\config.xml'
    [xml]$config = Get-Content -LiteralPath $configFile -Raw
    $config.SelectSingleNode("//string[@name='campus_origin']").InnerText = $uri.GetLeftPart([System.UriPartial]::Authority)
    $config.Save($configFile)
}
$assets = Join-Path $build 'assets'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\..\web') -Destination $assets -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'android-files.js') -Destination $assets
$index = Join-Path $assets 'index.html'
$markup = [IO.File]::ReadAllText($index).Replace('</head>', '<script type="module" src="/android-files.js"></script></head>')
[IO.File]::WriteAllText($index,$markup,[Text.UTF8Encoding]::new($false))
Invoke-Checked "$bt\aapt.exe" @('package','-f','-M',"$PSScriptRoot\AndroidManifest.xml",'-S',$res,'-A',$assets,'-I',$platform,'-F',$unsigned)
Invoke-Checked "$Jdk\bin\jar.exe" @('uf',$unsigned,'-C',$dex,'classes.dex')
Invoke-Checked "$bt\zipalign.exe" @('-f','4',$unsigned,$aligned)
if (!(Test-Path -LiteralPath $key)) {
    Invoke-Checked "$Jdk\bin\keytool.exe" @('-genkeypair','-keystore',$key,'-storetype','JKS','-storepass',$StorePass,'-keypass',$KeyPass,'-alias',$KeyAlias,'-keyalg','RSA','-keysize','2048','-validity','3650','-dname','CN=Campus Cats Release')
}
Invoke-Checked "$bt\apksigner.bat" @('sign','--v4-signing-enabled','false','--ks',$key,'--ks-key-alias',$KeyAlias,'--ks-pass',"pass:$StorePass",'--key-pass',"pass:$KeyPass",'--out',$OutputApk,$aligned)
Invoke-Checked "$bt\apksigner.bat" @('verify','--verbose',$OutputApk)
Write-Host (Resolve-Path -LiteralPath $OutputApk)
