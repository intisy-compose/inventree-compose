#!/usr/bin/env bash
# shellcheck disable=SC2016 # patterns and fixtures hold a literal $
# The Linux CLI's tests: each case copies the CLI into a scratch stack and runs it against a fake
# docker, git, curl and python3 first on PATH, so nothing on the host is touched. Plain bash: an `ok`
# or `FAIL` line per case, non-zero exit on any failure.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repository=$(cd "$here/../.." && pwd)
fakes="$here/fakes"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
stack="$scratch/inventree-compose"
state="$scratch/state"
REAL_PYTHON3=$(command -v python3)
export REAL_PYTHON3

failures=0
case_name=""
case_failed=false
output=""
status=0
extra_path=""

new_stack() {
    rm -rf "$stack" "$state"
    mkdir -p "$stack/scripts" "$stack/data/backups" "$stack/data/media/part_images" "$state"
    cp "$repository/docker-compose.sh" "$repository/docker-compose.yml" "$repository/config.env.example" "$stack/"
    cp "$repository"/scripts/*.sh "$stack/scripts/"
    chmod +x "$stack/docker-compose.sh"
    : >"$state/calls"
    write_filled_config
}

write_filled_config() {
    printf '%s\n' TS_AUTHKEY=tskey-test TS_HOSTNAME=inventree INVENTREE_HOST= INVENTREE_ADMIN_USER=admin \
        INVENTREE_ADMIN_EMAIL=admin@localhost INVENTREE_ADMIN_PASSWORD=adminpass POSTGRES_PASSWORD=pg BACKUP_KEEP=48 >"$stack/config.env"
}

begin() {
    case_name=$1
    case_failed=false
    output=""
    extra_path=""
    new_stack
}

finish() {
    if $case_failed; then
        failures=$((failures + 1))
        printf '     %s\n' "${output//$'\n'/$'\n'     }"
    else
        echo "ok   $case_name"
    fi
}

# run_cli ARGUMENTS...: runs the scratch CLI with the fakes, keeping its output and exit code.
run_cli() {
    output=$(cd "$scratch" && PATH="${extra_path:+$extra_path:}$fakes:$PATH" FAKE_DOCKER_DIR="$state" FAKE_BACKUPS="$stack/data/backups" \
        bash "$stack/docker-compose.sh" "$@" 2>&1)
    status=$?
}

# without_sleep: the next run_cli waits no real time, so a retry loop runs through in an instant.
without_sleep() {
    mkdir -p "$scratch/no-sleep"
    printf '%s\n' '#!/bin/bash' 'exit 0' >"$scratch/no-sleep/sleep"
    chmod +x "$scratch/no-sleep/sleep"
    extra_path="$scratch/no-sleep"
}

check() {
    local description=$1
    shift
    if ! "$@"; then
        $case_failed || echo "FAIL $case_name"
        echo "     - $description"
        case_failed=true
    fi
}

status_is() { [ "$status" -eq "$1" ]; }
said() { grep -qF -- "$1" <<<"$output"; }
not_said() { ! said "$1"; }
called() { grep -qE -- "$1" "$state/calls"; }
not_called() { ! called "$1"; }
call_count_is() { [ "$(grep -cE -- "$1" "$state/calls")" -eq "$2" ]; }
config_has() { grep -qxF -- "$1" "$stack/config.env"; }

# called_before FIRST SECOND: the first call matching FIRST comes before the first matching SECOND.
called_before() {
    local first second
    first=$(grep -nE -- "$1" "$state/calls" | head -n 1 | cut -d: -f1)
    second=$(grep -nE -- "$2" "$state/calls" | head -n 1 | cut -d: -f1)
    [ -n "$first" ] && [ -n "$second" ] && [ "$first" -lt "$second" ]
}

# add_dump NAME [AGE_SECONDS]: a complete dump in the scratch stack's data/backups.
add_dump() {
    printf 'PGDMP fake dump' >"$stack/data/backups/$1"
    touch -d "@$(($(date +%s) - ${2:-600}))" "$stack/data/backups/$1"
}

set_state() { printf '%s\n' "${@:2}" >"$state/$1"; }

ps1_commands() {
    tr -d '\r' <"$repository/docker-compose.ps1" | awk '
        /^\$usage[[:space:]]*=[[:space:]]*@\{/ { inside = 1; next }
        inside && /^\}/ { exit }
        inside && /^[[:space:]]*"[^"]+"[[:space:]]*=/ { key = $0; sub(/^[[:space:]]*"/, "", key); sub(/".*/, "", key); print key }'
}

## Skeleton

begin "the usage lists every command of the ps1's usage table"
run_cli help
check "exits 1" status_is 1
while IFS= read -r command; do
    check "usage names $command" grep -qE "^  $command " <<<"$output"
done < <(ps1_commands)
finish

begin "the usage text is the ps1's, with ./docker-compose.sh, / paths and --fresh"
run_cli help
check "the command list" said "Usage: ./docker-compose.sh [backup|catalog|data|down|init-config|logs|prove-data|restart|restore|status|up|url]"
check "up with --fresh" said "  up           [--fresh]  join the tailnet, restore an empty database from data/backups, start the stack (default); --fresh starts it empty instead"
check "no PowerShell spelling" not_said "-Fresh"
check "no backslash path" not_said 'data\backups'
finish

begin "an unknown command shows the usage"
run_cli frobnicate
check "exits 1" status_is 1
check "prints the usage" said "Usage: ./docker-compose.sh ["
check "calls no docker" not_called .
finish

begin "an unknown option shows the usage and starts nothing"
run_cli up --bogus
check "exits 1" status_is 1
check "prints the usage" said "Usage: ./docker-compose.sh ["
check "calls no docker" not_called .
finish

begin "an empty command shows the usage instead of running up"
run_cli ""
check "exits 1" status_is 1
check "prints the usage" said "Usage: ./docker-compose.sh ["
check "calls no docker" not_called .
finish

begin "no command at all runs up"
run_cli
check "exits 0" status_is 0
check "starts the stack" called "^compose up -d$"
finish

begin "--fresh alone is not a command"
run_cli --fresh
check "exits 1" status_is 1
check "calls no docker" not_called .
finish

begin "the PowerShell spelling -Fresh is an unknown option"
run_cli up -Fresh
check "exits 1" status_is 1
check "calls no docker" not_called .
finish

begin "a command without options refuses one"
run_cli down --force
check "exits 1" status_is 1
check "calls no compose down" not_called "^compose down"
run_cli restore a.dump b.dump
check "restore takes one file at most" status_is 1
run_cli restore --fresh
check "restore takes no option" status_is 1
check "stops nothing" not_called "^compose stop"
finish

begin "rebuild is shelf's, not inventree's"
run_cli rebuild
check "exits 1" status_is 1
check "prints the usage" said "Usage: ./docker-compose.sh ["
check "calls no docker" not_called .
finish

begin "COMPOSE_PROJECT_NAME is unset"
output=$(cd "$scratch" && COMPOSE_PROJECT_NAME=elsewhere PATH="$fakes:$PATH" FAKE_DOCKER_DIR="$state" \
    bash "$stack/docker-compose.sh" status 2>&1)
check "docker never sees it" grep -qx unset "$state/compose-project-name"
finish

begin "the command is case-insensitive, as in the ps1"
run_cli STATUS
check "runs compose ps -a" called "^compose ps -a$"
finish

begin "every command without the stack dispatches to its compose call"
run_cli down
check "down runs compose down" called "^compose down$"
check "down says so" said "Stopping everything..."
run_cli status
check "status runs compose ps -a" called "^compose ps -a$"
run_cli logs server
check "logs follows the named service" called "^compose logs -f server$"
finish

begin "url prints the tailnet URL and the sign-in from config.env"
sed -i 's/^INVENTREE_HOST=.*/INVENTREE_HOST=inventree.tail-test.ts.net/' "$stack/config.env"
run_cli url
check "exits 0" status_is 0
check "prints the tailnet URL" said "  InvenTree : https://inventree.tail-test.ts.net   (from any device on your tailnet)"
check "prints the local URL" said "  Locally   : http://localhost:8441   (this PC only)"
check "prints the sign-in" said "  Sign in   : admin / the INVENTREE_ADMIN_PASSWORD in config.env"
finish

begin "a command that needs config.env refuses without one"
rm "$stack/config.env"
run_cli backup
check "exits 1" status_is 1
check "names init-config" said "No config.env - run './docker-compose.sh init-config' first."
finish

begin "a missing secret or admin user is named"
sed -i -e 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=/' -e 's/^INVENTREE_ADMIN_USER=.*/INVENTREE_ADMIN_USER=/' "$stack/config.env"
run_cli up
check "exits 1" status_is 1
check "names both" said "config.env is missing: POSTGRES_PASSWORD, INVENTREE_ADMIN_USER - run init-config."
check "starts nothing" not_called "^compose up"
finish

## init-config

begin "init-config creates config.env with both secrets, with LF endings"
rm "$stack/config.env"
run_cli init-config
check "exits 0" status_is 0
check "names both" said "Generated INVENTREE_ADMIN_PASSWORD, POSTGRES_PASSWORD in config.env."
for name in INVENTREE_ADMIN_PASSWORD POSTGRES_PASSWORD; do
    check "$name is 48 lowercase hex, as the ps1's 24 bytes" grep -qxE "$name=[0-9a-f]{48}" "$stack/config.env"
done
check "no CR byte" [ "$(tr -cd '\r' <"$stack/config.env" | wc -c)" -eq 0 ]
check "the example's comments stay" grep -qF "# How many hourly database dumps data/backups keeps." "$stack/config.env"
check "the admin user from the example" config_has INVENTREE_ADMIN_USER=admin
finish

begin "config.env holds secrets, so it is created 0600 and stays 0600 when rewritten"
if [ -n "${MSYSTEM:-}" ]; then
    echo "skip $case_name: Git Bash on NTFS has no file modes"
else
    rm "$stack/config.env"
    chmod 0644 "$stack/config.env.example"
    run_cli init-config
    check "created 0600" [ "$(stat -c %a "$stack/config.env")" = 600 ]
    sed -i 's/^TS_AUTHKEY=.*/TS_AUTHKEY=tskey-test/' "$stack/config.env"
    run_cli up
    check "the tailnet rewrite happened" config_has INVENTREE_HOST=inventree.tail-test.ts.net
    check "still 0600 after the rewrite" [ "$(stat -c %a "$stack/config.env")" = 600 ]
    finish
fi

begin "init-config keeps existing values and fills only the empty ones"
printf '%s\r\n' "# kept comment" TS_AUTHKEY=tskey-mine INVENTREE_ADMIN_USER=me INVENTREE_ADMIN_PASSWORD=mine \
    POSTGRES_PASSWORD= 'DESIGN_DIRS="D:\designs;E:\more"' >"$stack/config.env"
run_cli init-config
check "names only the generated one" said "Generated POSTGRES_PASSWORD in config.env."
check "INVENTREE_ADMIN_PASSWORD kept" config_has INVENTREE_ADMIN_PASSWORD=mine
check "INVENTREE_ADMIN_USER kept" config_has INVENTREE_ADMIN_USER=me
check "TS_AUTHKEY kept" config_has TS_AUTHKEY=tskey-mine
check "a quoted value with backslashes kept" config_has 'DESIGN_DIRS="D:\designs;E:\more"'
check "the comment kept" config_has "# kept comment"
check "POSTGRES_PASSWORD filled" grep -qxE "POSTGRES_PASSWORD=[0-9a-f]{48}" "$stack/config.env"
check "CRLF became LF" [ "$(tr -cd '\r' <"$stack/config.env" | wc -c)" -eq 0 ]
finish

begin "init-config with every secret changes nothing"
cp "$stack/config.env" "$scratch/before.env"
run_cli init-config
check "says so" said "config.env already has every secret; nothing changed."
check "the file is unchanged" cmp -s "$scratch/before.env" "$stack/config.env"
finish

## The restore decision in up and restart

begin "a dump docker cannot probe stops up before anything starts, instead of restoring an older one"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 600
set_state probe-fails inventree-20261002-000000.dump
run_cli up
check "exits 1" status_is 1
check "names the dump and the docker exit" said "docker could not run pg_restore --list on inventree-20261002-000000.dump (exit 125)"
check "says nothing was started" said "Nothing was started, because a dump in data/backups could not be checked; run ./docker-compose.sh up again"
check "no compose up at all" not_called "^compose up"
check "never restores the older dump" not_called "pg_restore -h db"
finish

begin "exit 126 and 127 of the probe stop up too, exit 1 is a bad dump"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 600
set_state probe-fails inventree-20261002-000000.dump
set_state probe-exit 127
run_cli up
check "127 stops" status_is 1
set_state probe-exit 126
run_cli restart
check "126 stops restart" status_is 1
check "and names restart" said "run ./docker-compose.sh restart again"
check "no compose up after either" not_called "^compose up"
set_state probe-exit 1
run_cli up
check "1 skips that dump and restores the older" called "pg_restore -h db .*/backups/inventree-20261001-000000.dump$"
check "and says why it skipped" said "skipping inventree-20261002-000000.dump: pg_restore cannot list it (exit 1)"
finish

begin "the probe runs pg_restore --list in the db-backup service's image over data/backups read-only"
add_dump inventree-20261001-000000.dump
run_cli up
check "the pinned image from docker-compose.yml" called "^run --rm -v .*/data/backups:/backups:ro postgres:17\.10-alpine pg_restore --list /backups/inventree-20261001-000000\.dump$"
finish

begin "Refuse: every dump rejected prints each with its reason and starts nothing"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 3600
set_state unlistable inventree-20261002-000000.dump
set_state no-table-data inventree-20261001-000000.dump
run_cli up
check "exits 1" status_is 1
check "names the empty volume" said "The database volume inventree-compose_inventree-db is empty, but no dump in data/backups can be restored:"
check "the unlistable dump with its reason" said "  inventree-20261002-000000.dump: pg_restore cannot list it (exit 1)"
check "the empty hourly dump with its reason" said "  inventree-20261001-000000.dump: it holds no table data"
check "the way on is --fresh" said "or start with an empty database on purpose: ./docker-compose.sh up --fresh"
check "no compose up at all" not_called "^compose up"
check "not even the tailnet" not_called "tailscale"
finish

begin "an empty hourly dump is skipped for an older one that holds data"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 600
set_state no-table-data inventree-20261002-000000.dump
run_cli up
check "exits 0" status_is 0
check "says it skipped the empty one" said "  skipping inventree-20261002-000000.dump: it holds no table data"
check "restores the older" called "pg_restore -h db -U inventree -d inventree --clean --if-exists /backups/inventree-20261001-000000.dump$"
finish

begin "Refuse names the verb it refused"
add_dump inventree-20261001-000000.dump
set_state unlistable inventree-20261001-000000.dump
run_cli restart
check "exits 1" status_is 1
check "the way on is restart --fresh" said "./docker-compose.sh restart --fresh"
check "no compose up at all" not_called "^compose up"
finish

begin "a dumps folder that cannot be listed refuses"
add_dump inventree-20261001-000000.dump
mkdir -p "$scratch/failing-bin"
printf '%s\n' '#!/bin/bash' 'echo "find: permission denied" >&2' 'exit 1' >"$scratch/failing-bin/find"
chmod +x "$scratch/failing-bin/find"
output=$(cd "$scratch" && PATH="$scratch/failing-bin:$fakes:$PATH" FAKE_DOCKER_DIR="$state" FAKE_BACKUPS="$stack/data/backups" \
    bash "$stack/docker-compose.sh" up 2>&1)
status=$?
check "exits 1" status_is 1
check "names the folder" said "/data/backups: it cannot be listed"
check "no compose up at all" not_called "^compose up"
finish

begin "--fresh on an empty volume restores nothing and warns about BACKUP_KEEP"
add_dump inventree-20261001-000000.dump
run_cli up --fresh
check "exits 0" status_is 0
check "says it starts empty" said "Starting with an empty database (--fresh)."
check "warns about BACKUP_KEEP" said "rotate the old dumps out after BACKUP_KEEP hours unless './docker-compose.sh restore <file>' runs first."
check "no pg_restore" not_called "pg_restore -h"
check "never probes a dump" not_called "pg_restore --list"
check "starts the stack" called "^compose up -d$"
finish

begin "--fresh with no dumps says so without the warning"
run_cli up --fresh
check "exits 0" status_is 0
check "says it starts empty" said "Starting with an empty database (--fresh)."
check "no BACKUP_KEEP warning" not_said "BACKUP_KEEP"
finish

begin "restart --fresh starts empty too"
add_dump inventree-20261001-000000.dump
run_cli restart --fresh
check "exits 0" status_is 0
check "says it starts empty" said "Starting with an empty database (--fresh)."
check "no pg_restore" not_called "pg_restore -h"
check "recreates" called "^compose up -d --force-recreate$"
finish

begin "a volume holding a cluster is kept, --fresh or not"
set_state volume cluster
add_dump inventree-20261001-000000.dump
run_cli up --fresh
check "exits 0" status_is 0
check "no pg_restore" not_called "pg_restore -h"
check "no separate database start" not_called "^compose up -d db db-backup$"
check "no fresh message" not_said "Starting with an empty database"
run_cli up
check "without --fresh too" not_called "pg_restore -h"
finish

begin "Docker not answering keeps the volume"
set_state volume unreachable
add_dump inventree-20261001-000000.dump
run_cli up
check "exits 0" status_is 0
check "no pg_restore" not_called "pg_restore -h"
finish

begin "Restore happens before the server starts: tailnet, then only db and db-backup, then the full up"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 600
set_state unlistable inventree-20261002-000000.dump
run_cli up
check "exits 0" status_is 0
check "prints the skipped dump with its reason" said "  skipping inventree-20261002-000000.dump: pg_restore cannot list it (exit 1)"
check "names the dump and its age" said "Restoring inventree-20261001-000000.dump (2 h 0 min old) into the empty database..."
check "the tailnet first" called_before "^compose up -d tailscale$" "^compose up -d db db-backup$"
check "db and db-backup before the restore" called_before "^compose up -d db db-backup$" "pg_isready"
check "the database reachable before the restore" called_before "pg_isready -h db -U inventree -d inventree" "pg_restore -h db"
check "restores the older dump" called "^compose exec -T db-backup pg_restore -h db -U inventree -d inventree --clean --if-exists /backups/inventree-20261001-000000.dump$"
check "the full up, which starts the server, only after the restore" called_before "pg_restore -h db" "^compose up -d$"
check "no server exec before the restore" called_before "pg_restore -h db" "^compose exec -T server"
check "says it restored" said "Restored inventree-20261001-000000.dump."
check "says InvenTree starts after it" said "Starting InvenTree..."
finish

begin "a failed pg_restore stops the stack and removes the volume it created"
add_dump inventree-20261001-000000.dump
set_state pg-restore-exit 1
run_cli up
check "exits 1" status_is 1
check "names the failure" said "pg_restore reported errors (exit 1); check the output above."
check "says what it removes" said "Stopping the stack and removing inventree-compose_inventree-db, which was empty before this run..."
check "down before volume rm" called_before "^compose down$" "^volume rm inventree-compose_inventree-db$"
check "never the full up" not_called "^compose up -d$"
check "names the retry" said "Restoring inventree-20261001-000000.dump failed. Run ./docker-compose.sh up to try again, or start empty and restore by hand:"
check "names the manual way" said "  ./docker-compose.sh up --fresh   then   ./docker-compose.sh restore inventree-20261001-000000.dump"
check "no removal failure claimed" not_said "Could not remove"
finish

begin "a failed volume removal after a failed restore is said"
add_dump inventree-20261001-000000.dump
set_state pg-restore-exit 1
set_state volume-rm-exit 1
run_cli up
check "exits 1" status_is 1
check "says the volume could not be removed" said "Could not remove inventree-compose_inventree-db; remove it (docker volume rm inventree-compose_inventree-db) before the next up."
finish

begin "a database that does not start rolls back too"
add_dump inventree-20261001-000000.dump
set_state up-db-exit 1
run_cli up
check "exits 1" status_is 1
check "names the failure" said "The database did not start."
check "removes the volume" called "^volume rm inventree-compose_inventree-db$"
finish

begin "restart restores like up, then recreates"
add_dump inventree-20261001-000000.dump
run_cli restart
check "exits 0" status_is 0
check "restores first" called_before "pg_restore -h db" "^compose up -d --force-recreate$"
check "says it recreates" said "Recreating..."
finish

begin "a failed restore under restart rolls back as under up"
add_dump inventree-20261001-000000.dump
set_state pg-restore-exit 2
run_cli restart
check "exits 1" status_is 1
check "removes the volume" called "^volume rm inventree-compose_inventree-db$"
check "never recreates" not_called "^compose up -d --force-recreate$"
finish

## Static files and plugins

begin "up collects the static files on a fresh volume, then the plugins"
set_state web-index 0
run_cli up
check "exits 0" status_is 0
check "says so" said "Collecting static files..."
check "runs invoke static after the full up" called_before "^compose up -d$" "^compose exec -T server invoke static$"
check "collects the plugins after" called_before "^compose exec -T server invoke static$" "^compose exec -T server sh -c cd /home/inventree/src/backend/InvenTree && python manage.py collectplugins$"
check "prints the URLs" said "  InvenTree : https://inventree.tail-test.ts.net"
finish

begin "up with the web UI collected skips invoke static but still collects the plugins"
run_cli up
check "exits 0" status_is 0
check "no invoke static" not_called "invoke static"
check "no collecting message" not_said "Collecting static files..."
check "collects the plugins" called "manage.py collectplugins$"
finish

begin "a server exec that answers nothing counts as no web UI, as the ps1's [int] of empty"
set_state web-index ''
run_cli up
check "runs invoke static" called "^compose exec -T server invoke static$"
finish

begin "a failed invoke static or collectplugins is survived with a warning"
set_state web-index 0
set_state static-exit 1
set_state collectplugins-exit 2
run_cli up
check "exits 0" status_is 0
check "warns about invoke static" said "Warning: invoke static failed; the web UI may be served without its assets."
check "warns about collectplugins" said "Warning: collectplugins failed; the browser may keep the plugins' old static files."
check "still prints the URLs" said "InvenTree : https://"
finish

begin "steps that work print no warning"
set_state web-index 0
run_cli up
check "no warning" not_said "Warning:"
finish

begin "restart collects the plugins too"
run_cli restart
check "exits 0" status_is 0
check "collects the plugins after the recreate" called_before "^compose up -d --force-recreate$" "manage.py collectplugins$"
finish

begin "a failed up starts no collection and prints no URLs"
set_state up-exit 1
run_cli up
check "exits non-zero" [ "$status" -ne 0 ]
check "no server exec" not_called "^compose exec -T server"
check "no URLs" not_said "InvenTree : https://"
finish

begin "a failed recreate skips the collection, still prints the URLs and fails"
set_state recreate-exit 1
run_cli restart
check "exits 1" status_is 1
check "no server exec" not_called "^compose exec -T server"
check "prints the URLs as the ps1 does" said "InvenTree : https://"
finish

## Tailnet

begin "up writes INVENTREE_HOST once joined"
run_cli up
check "says it joined" said "Joined as inventree.tail-test.ts.net"
check "INVENTREE_HOST" config_has INVENTREE_HOST=inventree.tail-test.ts.net
check "says it wrote it" said "Wrote INVENTREE_HOST to config.env."
check "the tailnet before the full up" called_before "^compose up -d tailscale$" "^compose up -d$"
run_cli up
check "the second up writes nothing" call_count_is "^compose up -d tailscale$" 2
check "and says nothing about writing" not_said "Wrote INVENTREE_HOST"
finish

begin "up without TS_AUTHKEY and without a node identity stops"
sed -i 's/^TS_AUTHKEY=.*/TS_AUTHKEY=/' "$stack/config.env"
run_cli up
check "exits 1" status_is 1
check "says so" said "TS_AUTHKEY is empty in config.env and this node has not joined the tailnet yet."
check "starts nothing" not_called "^compose up"
finish

begin "a node identity on disk needs no TS_AUTHKEY"
sed -i 's/^TS_AUTHKEY=.*/TS_AUTHKEY=/' "$stack/config.env"
mkdir -p "$stack/data/tailscale"
: >"$stack/data/tailscale/tailscaled.state"
run_cli up
check "exits 0" status_is 0
finish

## Manual restore, backup, data, catalog

begin "restore refuses without db and db-backup running"
add_dump inventree-20261001-000000.dump
set_state running gateway
run_cli restore
check "exits 1" status_is 1
check "names both" said "Cannot restore: db, db-backup not running. Run ./docker-compose.sh up first, or ./docker-compose.sh up --fresh and then restore."
check "stops nothing" not_called "^compose stop"
finish

begin "restore names only the service that is not running"
add_dump inventree-20261001-000000.dump
set_state running db gateway
run_cli restore
check "names db-backup" said "Cannot restore: db-backup not running."
finish

begin "restore takes the newest restorable dump and restarts only after pg_restore"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 600
set_state no-table-data inventree-20261002-000000.dump
set_state running db db-backup server
run_cli restore
check "exits 0" status_is 0
check "says what it restores" said "Restoring inventree-20261001-000000.dump (InvenTree is stopped meanwhile)..."
check "stops the app services first" called_before "^compose stop gateway worker server$" "pg_restore -h db"
check "restores the older dump" called "pg_restore -h db -U inventree -d inventree --clean --if-exists /backups/inventree-20261001-000000.dump$"
check "starts the stack after" called_before "pg_restore -h db" "^compose up -d$"
check "says it restored" said "Restored inventree-20261001-000000.dump."
finish

begin "a failed manual restore leaves the app stopped"
add_dump inventree-20261001-000000.dump
set_state running db db-backup
set_state pg-restore-exit 3
run_cli restore
check "exits 1" status_is 1
check "says so" said "pg_restore reported errors (exit 3); check the output above. gateway, worker and server stay stopped."
check "no up after" not_called "^compose up -d$"
finish

begin "restore of a named file probes it, then restores it by its name only"
add_dump inventree-20261003-000000.dump
set_state running db db-backup
run_cli restore data/backups/inventree-20261003-000000.dump
check "exits 0" status_is 0
check "probes it first" called_before "pg_restore --list /backups/inventree-20261003-000000.dump$" "^compose stop gateway worker server$"
check "restores that file" called "--clean --if-exists /backups/inventree-20261003-000000.dump$"
check "says it restored" said "Restored inventree-20261003-000000.dump."
finish

begin "restore of a named file that is not in data/backups stops nothing"
add_dump inventree-20261001-000000.dump
set_state running db db-backup
run_cli restore inventree-2026100-000000.dump
check "exits 1" status_is 1
check "says so" said "No dump named inventree-2026100-000000.dump in data/backups; nothing was stopped."
check "stops nothing" not_called "^compose stop"
check "restores nothing" not_called "pg_restore -h db"
finish

begin "restore of a named dump without table data stops nothing"
add_dump inventree-20261001-000000.dump
set_state no-table-data inventree-20261001-000000.dump
set_state running db db-backup
run_cli restore inventree-20261001-000000.dump
check "exits 1" status_is 1
check "names the reason" said "inventree-20261001-000000.dump cannot be restored: it holds no table data; nothing was stopped."
check "stops nothing" not_called "^compose stop"
check "restores nothing" not_called "pg_restore -h db"
finish

begin "restore of a named dump docker cannot probe stops nothing"
add_dump inventree-20261001-000000.dump
set_state probe-fails inventree-20261001-000000.dump
set_state running db db-backup
run_cli restore inventree-20261001-000000.dump
check "exits 1" status_is 1
check "names the docker exit" said "docker could not run pg_restore --list on inventree-20261001-000000.dump (exit 125)"
check "stops nothing" not_called "^compose stop"
finish

begin "restore without any dump says so"
set_state running db db-backup
run_cli restore
check "exits 1" status_is 1
check "says so" said "No backups in data/backups."
finish

begin "restore with every dump rejected names the last reason"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 600
set_state no-table-data 'inventree-*.dump'
set_state running db db-backup
run_cli restore
check "exits 1" status_is 1
check "names the last dump checked and why" said "No dump in data/backups can be restored; the last one checked, inventree-20261001-000000.dump: it holds no table data."
check "does not claim there are none" not_said "No backups in data/backups."
check "stops nothing" not_called "^compose stop"
finish

begin "restore stops when docker cannot probe a dump"
add_dump inventree-20261001-000000.dump 7200
add_dump inventree-20261002-000000.dump 600
set_state probe-fails inventree-20261002-000000.dump
set_state running db db-backup
run_cli restore
check "exits 1" status_is 1
check "names the docker exit" said "docker could not run pg_restore --list on inventree-20261002-000000.dump (exit 125)"
check "stops nothing" not_called "^compose stop"
check "restores nothing" not_called "pg_restore -h db"
finish

begin "backup writes a .tmp, then renames it"
run_cli backup
check "exits 0" status_is 0
check "pg_dump to .tmp, then mv" called '^compose exec -T db-backup sh -c pg_dump -h db -U inventree -d inventree -Fc -f /backups/inventree-[0-9]{8}-[0-9]{6}\.dump\.tmp && mv /backups/inventree-[0-9]{8}-[0-9]{6}\.dump\.tmp /backups/inventree-[0-9]{8}-[0-9]{6}\.dump$'
check "says where" said "Backed up to data/backups/inventree-"
finish

begin "a failed backup says so"
set_state backup-exit 1
run_cli backup
check "exits 1" status_is 1
check "says so" said "Backup failed."
finish

begin "data status and use point the submodule"
run_cli data
check "status by default" called "^git -C .* submodule status -- data$"
run_cli data use someone/inventree-data@v2
check "the GitHub URL" called "^git -C .* config submodule.data.url https://github.com/someone/inventree-data.git$"
check "fetches the ref" called "^git -C .*/data fetch -q origin v2$"
check "says where data is" said "data now at 0abc123"
run_cli data use
check "no source is the template from .gitmodules" called "^git -C .* config submodule.data.url https://github.com/intisy-compose/inventree-data-template.git$"
run_cli data bogus
check "an unknown subcommand shows the usage" status_is 1
finish

begin "catalog runs python3 scripts/catalog.py with its arguments"
run_cli catalog previews DS-1
check "exits 0" status_is 0
check "python3 with the arguments" called "^python3 catalog.py previews DS-1$"
finish

begin "catalog needs config.env"
rm "$stack/config.env"
run_cli catalog sync
check "exits 1" status_is 1
check "never runs the catalog" not_called "catalog.py"
finish

## prove-data

prove_ready() {
    set_state containers inventree-server inventree-db-backup
    set_state volume cluster
    set_state volumes inventree-compose_inventree-db inventree-compose_inventree-files other-compose_db
    set_state counts-1 'public.part_part|12' 'public.stock_stockitem|40' 'public.django_q_ormq|3' 'public.django_q_task|1000'
    set_state counts-2 'public.part_part|12' 'public.stock_stockitem|40' 'public.django_q_ormq|0' 'public.django_q_task|998'
    printf 'png' >"$stack/data/media/part_images/b-part.png"
    printf 'png' >"$stack/data/media/part_images/a-part.preview.png"
    printf 'png' >"$stack/data/media/part_images/a-part.thumbnail.png"
}

begin "prove-data refuses when a container is not running"
set_state containers inventree-db-backup
run_cli prove-data
check "exits 1" status_is 1
check "names it" said "inventree-server is not running; start the stack first"
check "no backup" not_called "pg_dump"
check "nothing removed" not_called "^volume rm"
finish

begin "prove-data refuses without a part image to fetch"
prove_ready
rm "$stack"/data/media/part_images/b-part.png
run_cli prove-data
check "exits 1" status_is 1
check "says so" said "no part image in data/media/part_images to fetch"
check "no backup" not_called "pg_dump"
finish

begin "prove-data refuses when no API token can be taken"
prove_ready
: >"$state/token-fails"
run_cli prove-data
check "exits 1" status_is 1
check "no backup" not_called "pg_dump"
check "nothing removed" not_called "^volume rm"
finish

begin "prove-data deletes nothing when the newest dump is not restorable"
prove_ready
set_state no-table-data 'inventree-*.dump'
run_cli prove-data
check "exits 1" status_is 1
check "says nothing was deleted" said "cannot be listed by pg_restore or holds no table data; nothing was deleted"
check "no down" not_called "^compose down"
check "nothing removed" not_called "^volume rm"
finish

begin "prove-data deletes nothing when docker cannot probe the newest dump"
prove_ready
set_state probe-fails 'inventree-*.dump'
run_cli prove-data
check "exits 1" status_is 1
check "names the docker exit" said "(exit 125)"
check "no down" not_called "^compose down"
check "nothing removed" not_called "^volume rm"
finish

begin "prove-data deletes nothing when no table was counted"
prove_ready
set_state counts-1 ''
run_cli prove-data
check "exits 1" status_is 1
check "says so" said "no table was counted; nothing was deleted"
check "no down" not_called "^compose down"
check "nothing removed" not_called "^volume rm"
finish

begin "prove-data passes, leaving django_q_ormq and django_q_task uncompared and other projects' volumes alone"
prove_ready
run_cli prove-data
check "exits 0" status_is 0
check "takes the token before anything" called_before "^curl http://localhost:8441/api/user/token/ Authorization: Basic YWRtaW46YWRtaW5wYXNz$" "pg_dump"
check "takes a fresh dump first" called_before "pg_dump" "^compose down$"
check "counts 4 tables before" said "4 tables, dump inventree-"
check "removes only this stack's volumes" called "^volume rm inventree-compose_inventree-db inventree-compose_inventree-files$"
check "never another project's" not_called "other-compose_db"
check "restores the fresh dump into the emptied volume" called "pg_restore -h db .*/backups/inventree-[0-9]{8}-[0-9]{6}\.dump$"
check "waits for the API with the old token" called "^curl http://localhost:8441/api/user/me/ Authorization: Token inv-0123456789abcdef$"
check "prints django_q_ormq uncompared" said "public.django_q_ormq (not compared) before=3 after=0"
check "prints django_q_task uncompared" said "public.django_q_task (not compared) before=1000 after=998"
check "all tables match" said "all 4 tables match"
check "fetches the first part image, not a preview or thumbnail" called "^curl http://localhost:8441/media/part_images/b-part.png Authorization: Token inv-0123456789abcdef$"
check "the image answered" said "part image answered 200"
check "says every table came back" said "every table came back"
finish

begin "prove-data names each differing table and the way back, and still checks the image"
prove_ready
set_state counts-2 'public.part_part|11' 'public.django_q_task|3'
run_cli prove-data
check "exits 1" status_is 1
check "the differing count" said "DIFFERS public.part_part before=12 after=11"
check "the missing table" said "DIFFERS public.stock_stockitem before=40 after=missing"
check "the recovery hint" said "The volumes were deleted. Recover with: ./docker-compose.sh up"
check "the manual way" said "If that keeps failing: ./docker-compose.sh up --fresh   then   ./docker-compose.sh restore inventree-"
check "the image is still fetched" called "/media/part_images/b-part.png"
check "never says every table came back" not_said "every table came back"
finish

begin "prove-data fails on an image that is not served, though the data is back"
prove_ready
set_state image-status 404
run_cli prove-data
check "exits 1" status_is 1
check "the tables match" said "all 4 tables match"
check "names the status" said "part image answered 404"
check "says the data is back" said "The image check failed; the data is back."
finish

begin "prove-data waits out an API that does not answer yet"
prove_ready
set_state api-status 000 000 502 200
without_sleep
run_cli prove-data
check "exits 0" status_is 0
check "asks until it answers 200" call_count_is "/api/user/me/" 4
check "says every table came back" said "every table came back"
finish

begin "prove-data never puts a credential on curl's command line"
prove_ready
run_cli prove-data
check "exits 0" status_is 0
check "no credential on argv" not_called "CREDENTIAL ON ARGV"
check "the fake would catch one" bash -c 'FAKE_DOCKER_DIR="$1" "$2/curl" -H "Authorization: Token x" http://localhost:8441/api/user/me/ </dev/null >/dev/null; [ $? -eq 99 ]' _ "$state" "$fakes"
finish

begin "prove-data fails at once when the restored API rejects the old token"
prove_ready
set_state api-status 401
run_cli prove-data
check "exits 1" status_is 1
check "says so" said "the API token taken before the delete was rejected (401) after the restore"
check "the recovery hint" said "The volumes were deleted. Recover with: ./docker-compose.sh up"
check "asks only once" call_count_is "/api/user/me/" 1
finish

begin "prove-data with no volume of its own deletes nothing and gives the hint"
prove_ready
set_state volumes other-compose_db
run_cli prove-data
check "exits 1" status_is 1
check "says none was found" said "no volume labelled com.docker.compose.project=inventree-compose was found"
check "nothing removed" not_called "^volume rm"
check "the recovery hint" said "Recover with: ./docker-compose.sh up"
finish

echo
if [ "$failures" -eq 0 ]; then echo "all cases pass"; else echo "$failures cases fail"; fi
[ "$failures" -eq 0 ]
