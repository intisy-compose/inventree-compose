# Dot-source only. Needs docker-compose.ps1's Invoke-Backup, Read-Config and data-on-disk.ps1.

$ProveProject = "inventree-compose"
$ProveBackupContainer = "inventree-db-backup"
$ProveServerContainer = "inventree-server"
$ProveImageBaseUrl = "http://localhost:8441"
$ProveReadyTimeoutMinutes = 15

<#
.SYNOPSIS
Table-by-table differences between two row-count maps, as printable lines; empty when they match.
#>
function Compare-TableCounts([System.Collections.IDictionary]$Before, [System.Collections.IDictionary]$After) {
    $differences = @()
    foreach ($name in (@($Before.Keys) + @($After.Keys) | Sort-Object -Unique)) {
        $beforeCount = if ($Before.Contains($name)) { $Before[$name] } else { "missing" }
        $afterCount = if ($After.Contains($name)) { $After[$name] } else { "missing" }
        if ("$beforeCount" -ne "$afterCount") { $differences += "$name before=$beforeCount after=$afterCount" }
    }
    return $differences
}

function Get-InventreeTableCounts {
    return Get-TableRowCounts $ProveBackupContainer "db" "inventree" "inventree"
}

function Test-ContainerIsRunning([string]$Name) {
    return [bool](docker ps -q --filter "name=^$Name$")
}

function Invoke-Stack([string]$Verb) {
    & (Join-Path $PSScriptRoot "..\docker-compose.ps1") $Verb
    if ($LASTEXITCODE -ne 0) { throw "docker-compose.ps1 $Verb failed with exit code $LASTEXITCODE" }
}

<#
.SYNOPSIS
Names of this stack's own volumes, matched by compose project label and re-checked by name prefix.
.NOTES
Never returns a volume of another project, whatever the label filter says.
#>
function Get-StackVolumes {
    $names = @(docker volume ls -q --filter "label=com.docker.compose.project=$ProveProject")
    if ($LASTEXITCODE -ne 0) { throw "could not list the volumes of $ProveProject" }
    return @($names | Where-Object { $_ -and $_.StartsWith("${ProveProject}_") })
}

function Remove-StackVolumes {
    $volumes = Get-StackVolumes
    if (-not $volumes) { throw "no volume labelled com.docker.compose.project=$ProveProject was found" }
    $volumes | ForEach-Object { Write-Host "  removing $_" -ForegroundColor Gray }
    docker volume rm @volumes
    if ($LASTEXITCODE -ne 0) { throw "could not remove the volumes of $ProveProject" }
}

function Get-PartImageName {
    $folder = Join-Path $PSScriptRoot "..\data\media\part_images"
    $image = Get-ChildItem -LiteralPath $folder -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch "\.(preview|thumbnail)\." } | Select-Object -First 1
    if (-not $image) { throw "no part image in data\media\part_images to fetch" }
    return $image.Name
}

function Get-ApiToken {
    $config = Read-Config
    $pair = "$($config['INVENTREE_ADMIN_USER']):$($config['INVENTREE_ADMIN_PASSWORD'])"
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
    $response = Invoke-WebRequest -UseBasicParsing -Uri "$ProveImageBaseUrl/api/user/token/" -Headers @{ Authorization = "Basic $basic" }
    return ($response.Content | ConvertFrom-Json).token
}

function Wait-ForApiToken {
    $deadline = (Get-Date).AddMinutes($ProveReadyTimeoutMinutes)
    while ((Get-Date) -lt $deadline) {
        try { return Get-ApiToken } catch { Start-Sleep -Seconds 10 }
    }
    throw "InvenTree did not answer for $ProveReadyTimeoutMinutes minutes"
}

function Get-ImageStatusCode([string]$Name, [string]$Token) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$ProveImageBaseUrl/media/part_images/$Name" -Headers @{ Authorization = "Token $Token" }
        return [int]$response.StatusCode
    }
    catch [System.Net.WebException] {
        if (-not $_.Exception.Response) { throw }
        return [int]$_.Exception.Response.StatusCode
    }
}

<#
.SYNOPSIS
Prove that deleting every volume of the stack loses nothing: dump, count, delete, start, count, fetch a part image.
.NOTES
DESTRUCTIVE: it deletes the stack's volumes. Run it only with the owner's go-ahead. A fresh dump is taken
right before the "before" count, so writes after an older dump cannot look like a failed restore.
#>
function Invoke-ProveData {
    foreach ($container in @($ProveBackupContainer, $ProveServerContainer)) {
        if (-not (Test-ContainerIsRunning $container)) { throw "$container is not running; start the stack first" }
    }
    $imageName = Get-PartImageName

    Write-Step "Writing a fresh dump ..."
    Invoke-Backup
    $newest = Get-NewestDump (Join-Path $PSScriptRoot "..\data\backups") "inventree-*.dump"
    if (-not $newest) { throw "no complete dump exists in data\backups" }

    Write-Step "Counting rows before ..."
    $before = Get-InventreeTableCounts
    Write-Host "  $($before.Count) tables, dump $($newest.Name)" -ForegroundColor Gray

    Write-Step "Stopping the stack and deleting its volumes ..."
    Invoke-Stack "down"
    Remove-StackVolumes

    Write-Step "Starting the stack and waiting for the self-restore ..."
    Invoke-Stack "up"
    $token = Wait-ForApiToken

    Write-Step "Counting rows after ..."
    $after = Get-InventreeTableCounts
    $differences = Compare-TableCounts $before $after
    if ($differences) {
        $differences | ForEach-Object { Write-Host "  DIFFERS $_" -ForegroundColor Red }
        exit 1
    }
    Write-Host "  all $($after.Count) tables match" -ForegroundColor Green

    Write-Step "Fetching part image $imageName ..."
    $statusCode = Get-ImageStatusCode $imageName $token
    if ($statusCode -ne 200) { Write-Err "part image answered $statusCode"; exit 1 }
    Write-OK "part image answered 200"
    Write-OK "every table came back"
}
