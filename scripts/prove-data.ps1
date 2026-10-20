# Dot-source only. Needs docker-compose.ps1's Invoke-Backup, Read-Config and data-on-disk.ps1.

$ProveProject = "inventree-compose"
$ProveBackupContainer = "inventree-db-backup"
$ProveServerContainer = "inventree-server"
$ProveImageBaseUrl = "http://localhost:8441"
$ProveReadyTimeoutMinutes = 15
$ProveUncomparedTables = @("public.django_q_ormq")

<#
.SYNOPSIS
Table-by-table differences between two row-count maps, as printable lines; empty when they match.
.NOTES
Tables in Uncompared are skipped; they are printed by Write-UncomparedCounts instead.
#>
function Compare-TableCounts([System.Collections.IDictionary]$Before, [System.Collections.IDictionary]$After, [string[]]$Uncompared = @()) {
    $differences = @()
    foreach ($name in (@($Before.Keys) + @($After.Keys) | Sort-Object -Unique)) {
        if ($name -in $Uncompared) { continue }
        $beforeCount = if ($Before.Contains($name)) { $Before[$name] } else { "missing" }
        $afterCount = if ($After.Contains($name)) { $After[$name] } else { "missing" }
        if ("$beforeCount" -ne "$afterCount") { $differences += "$name before=$beforeCount after=$afterCount" }
    }
    return $differences
}

<#
.SYNOPSIS
Prints the counts of the tables the comparison skips.
.NOTES
public.django_q_ormq is the worker's task queue, which it refills on every start, so a restore
legitimately ends with different rows than the dump held.
#>
function Write-UncomparedCounts([System.Collections.IDictionary]$Before, [System.Collections.IDictionary]$After) {
    foreach ($name in $ProveUncomparedTables) {
        $beforeCount = if ($Before.Contains($name)) { $Before[$name] } else { "missing" }
        $afterCount = if ($After.Contains($name)) { $After[$name] } else { "missing" }
        Write-Host "  $name (not compared) before=$beforeCount after=$afterCount" -ForegroundColor Gray
    }
}

function Get-InventreeTableCounts {
    return Get-TableRowCounts $ProveBackupContainer "db" "inventree" "inventree"
}

function Test-ContainerIsRunning([string]$Name) {
    return [bool](docker ps -q --filter "name=^$Name$")
}

<#
.SYNOPSIS
Runs a docker-compose.ps1 verb; only "down" has its exit code trusted.
.NOTES
After "up" the exit code belongs to whichever native call ran last inside it (collectplugins), not to
"up" itself, so success after "up" is judged by the API and the table counts instead.
#>
function Invoke-Stack([string]$Verb) {
    & (Join-Path $PSScriptRoot "..\docker-compose.ps1") $Verb
    if ($Verb -eq "down" -and $LASTEXITCODE -ne 0) { throw "docker-compose.ps1 down failed with exit code $LASTEXITCODE" }
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

function Get-HttpStatus([string]$Url, [string]$Token) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers @{ Authorization = "Token $Token" }
        return [int]$response.StatusCode
    }
    catch [System.Net.WebException] {
        if (-not $_.Exception.Response) { return $null }
        return [int]$_.Exception.Response.StatusCode
    }
}

<#
.SYNOPSIS
Waits until the API answers 200 to the token taken before the delete.
.NOTES
401 or 403 fails at once: the token row should have come back with the restore, so retrying cannot help.
Anything else, including a refused connection, means InvenTree is still starting.
#>
function Wait-ForApi([string]$Token) {
    $deadline = (Get-Date).AddMinutes($ProveReadyTimeoutMinutes)
    while ((Get-Date) -lt $deadline) {
        $status = Get-HttpStatus "$ProveImageBaseUrl/api/user/me/" $Token
        if ($status -eq 200) { return }
        if ($status -eq 401 -or $status -eq 403) { throw "the API token taken before the delete was rejected ($status) after the restore" }
        Start-Sleep -Seconds 10
    }
    throw "InvenTree did not answer for $ProveReadyTimeoutMinutes minutes"
}

function Get-ImageStatusCode([string]$Name, [string]$Token) {
    return Get-HttpStatus "$ProveImageBaseUrl/media/part_images/$Name" $Token
}

function Write-RecoveryHint([string]$DumpName) {
    Write-Err "The volumes were deleted. Recover with: .\docker-compose.ps1 up   then   .\docker-compose.ps1 restore $DumpName"
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
    $token = Get-ApiToken

    Write-Step "Writing a fresh dump ..."
    Invoke-Backup
    $newest = Get-NewestDump (Join-Path $PSScriptRoot "..\data\backups") "inventree-*.dump"
    if (-not $newest) { throw "no complete dump exists in data\backups" }
    if (-not (Test-DumpIsRestorable $newest)) { throw "$($newest.Name) cannot be listed by pg_restore or holds no table data; nothing was deleted" }

    Write-Step "Counting rows before ..."
    $before = Get-InventreeTableCounts
    Write-Host "  $($before.Count) tables, dump $($newest.Name)" -ForegroundColor Gray

    Write-Step "Stopping the stack and deleting its volumes ..."
    try {
        Invoke-Stack "down"
        Remove-StackVolumes

        Write-Step "Starting the stack and waiting for the self-restore ..."
        Invoke-Stack "up"
        Wait-ForApi $token

        Write-Step "Counting rows after ..."
        $after = Get-InventreeTableCounts
    }
    catch { Write-RecoveryHint $newest.Name; throw }
    Write-UncomparedCounts $before $after
    $differences = Compare-TableCounts $before $after $ProveUncomparedTables
    if ($differences) {
        $differences | ForEach-Object { Write-Host "  DIFFERS $_" -ForegroundColor Red }
        Write-RecoveryHint $newest.Name
    }
    else { Write-Host "  all $($after.Count) tables match" -ForegroundColor Green }

    Write-Step "Fetching part image $imageName ..."
    $statusCode = Get-ImageStatusCode $imageName $token
    $imageIsServed = $statusCode -eq 200
    if ($imageIsServed) { Write-OK "part image answered 200" }
    else {
        Write-Err "part image answered $statusCode"
        if (-not $differences) { Write-Err "The image check failed; the data is back." }
    }
    if ($differences -or -not $imageIsServed) { exit 1 }
    Write-OK "every table came back"
}
