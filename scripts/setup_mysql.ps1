param(
    [string]$Database = "vlogshield",
    [string]$AppUser = "vlogshield_user",
    [string]$HostName = "localhost",
    [int]$Port = 3306,
    [string]$MysqlExe = "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"
)

if (-not (Test-Path $MysqlExe)) {
    throw "mysql.exe was not found at $MysqlExe"
}

function Convert-SecureStringToPlainText {
    param([securestring]$Value)
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Escape-SqlLiteral {
    param([string]$Value)
    $Value.Replace("\", "\\").Replace("'", "''")
}

$rootPassword = Read-Host "MySQL root password" -AsSecureString
$appPassword = Read-Host "Password for app user '$AppUser'" -AsSecureString

$rootPasswordText = Convert-SecureStringToPlainText $rootPassword
$appPasswordText = Convert-SecureStringToPlainText $appPassword

$databaseSql = Escape-SqlLiteral $Database
$appUserSql = Escape-SqlLiteral $AppUser
$appPasswordSql = Escape-SqlLiteral $appPasswordText

$sql = @"
CREATE DATABASE IF NOT EXISTS ``$databaseSql`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$appUserSql'@'$HostName' IDENTIFIED BY '$appPasswordSql';
ALTER USER '$appUserSql'@'$HostName' IDENTIFIED BY '$appPasswordSql';
GRANT SELECT, INSERT, DELETE, CREATE ON ``$databaseSql``.* TO '$appUserSql'@'$HostName';
FLUSH PRIVILEGES;
"@

$tempSql = New-TemporaryFile
try {
    Set-Content -Path $tempSql -Value $sql -Encoding UTF8
    $env:MYSQL_PWD = $rootPasswordText
    Get-Content -Raw $tempSql | & $MysqlExe --host=$HostName --port=$Port --user=root --protocol=tcp
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL setup failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item -LiteralPath $tempSql -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
}

$envPath = Join-Path (Get-Location) ".env"
$envLines = @()
if (Test-Path $envPath) {
    $envLines = Get-Content $envPath
}

$settings = [ordered]@{
    "FLASK_ENV" = "development"
    "FLASK_DEBUG" = "1"
    "FLASK_APP" = "wsgi:app"
    "FLASK_RUN_HOST" = "0.0.0.0"
    "FLASK_RUN_PORT" = "5000"
    "MAX_UPLOAD_MB" = "16"
    "SCAN_RATE_LIMIT" = "10 per minute"
    "RATE_LIMIT_STORAGE_URI" = "memory://"
    "MYSQL_HOST" = $HostName
    "MYSQL_PORT" = [string]$Port
    "MYSQL_DATABASE" = $Database
    "MYSQL_USER" = $AppUser
    "MYSQL_PASSWORD" = $appPasswordText
}

$existingKeys = @{}
foreach ($line in $envLines) {
    if ($line -match "^\s*([^#=]+)=") {
        $existingKeys[$matches[1].Trim()] = $true
    }
}

$updated = foreach ($line in $envLines) {
    if ($line -match "^\s*([^#=]+)=") {
        $key = $matches[1].Trim()
        if ($settings.Contains($key)) {
            "$key=$($settings[$key])"
        }
        else {
            $line
        }
    }
    else {
        $line
    }
}

foreach ($key in $settings.Keys) {
    if (-not $existingKeys.ContainsKey($key)) {
        $updated += "$key=$($settings[$key])"
    }
}

Set-Content -Path $envPath -Value $updated -Encoding UTF8
Write-Host "MySQL database '$Database' is ready and .env has been updated."
