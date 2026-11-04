#!/bin/bash
# shellcheck disable=SC2154 # here, backups_folder and dump_pattern are docker-compose.sh's, which sources this
# The bash twin of prove-data.ps1. Source only; needs docker-compose.sh's invoke_backup,
# config_value and test_dump_is_restorable, and data-on-disk.sh.

prove_project="inventree-compose"
prove_backup_container="inventree-db-backup"
prove_server_container="inventree-server"
prove_image_base_url="http://localhost:8441"
prove_ready_timeout_minutes=15
prove_uncompared_tables=(public.django_q_ormq public.django_q_task)

# compare_table_counts BEFORE AFTER [UNCOMPARED...]: the table-by-table differences between two sets
# of "schema.table|count" lines, one printable line each; nothing when they match. Uncompared tables
# are skipped; write_uncompared_counts prints them instead.
compare_table_counts() {
    local before=$1 after=$2 name before_count after_count
    shift 2
    local -A before_counts=() after_counts=() skipped=()
    for name in "$@"; do skipped[$name]=1; done
    read_counts before_counts "$before"
    read_counts after_counts "$after"
    while IFS= read -r name; do
        if [ -z "$name" ] || [ -n "${skipped[$name]:-}" ]; then continue; fi
        before_count=${before_counts[$name]:-missing}
        after_count=${after_counts[$name]:-missing}
        [ "$before_count" = "$after_count" ] || echo "$name before=$before_count after=$after_count"
    done < <(printf '%s\n' "${!before_counts[@]}" "${!after_counts[@]}" | LC_ALL=C sort -u)
}

# read_counts ARRAY LINES: fills the associative ARRAY from "schema.table|count" lines.
# shellcheck disable=SC2034 # counts is a nameref: the caller's array is the one filled
read_counts() {
    local -n counts=$1
    local line
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        counts[${line%%|*}]=${line#*|}
    done <<<"$2"
}

# write_uncompared_counts BEFORE AFTER: prints the counts of the tables the comparison skips.
# public.django_q_ormq is the worker's task queue, which it refills on every start, and
# public.django_q_task its rotating history of finished tasks, which it adds to and trims from the
# moment it starts (998 after 1000 on 2026-11-03, 15 new rows within 20 minutes), so a restore
# legitimately ends with different rows than the dump held.
write_uncompared_counts() {
    local name
    local -A before_counts=() after_counts=()
    read_counts before_counts "$1"
    read_counts after_counts "$2"
    for name in "${prove_uncompared_tables[@]}"; do
        note "  $name (not compared) before=${before_counts[$name]:-missing} after=${after_counts[$name]:-missing}"
    done
}

get_inventree_table_counts() { table_row_counts "$prove_backup_container" db inventree inventree; }

test_container_is_running() { [ -n "$(docker ps -q --filter "name=^$1$")" ]; }

# invoke_stack VERB: runs a docker-compose.sh verb; only "down" has its exit code trusted, because
# success after `up` is judged by the API and the table counts instead.
invoke_stack() {
    local verb=$1 stack_exit=0
    "$here/docker-compose.sh" "$verb" || stack_exit=$?
    if [ "$verb" = down ] && [ "$stack_exit" -ne 0 ]; then
        err "docker-compose.sh down failed with exit code $stack_exit"
        return 1
    fi
}

# get_stack_volumes: this stack's own volumes, matched by compose project label and re-checked by name
# prefix, so a volume of another project is never named whatever the label filter says.
get_stack_volumes() {
    local names name
    names=$(docker volume ls -q --filter "label=com.docker.compose.project=$prove_project") || {
        err "could not list the volumes of $prove_project"
        return 1
    }
    while IFS= read -r name; do
        [[ $name == "${prove_project}_"* ]] && echo "$name"
    done <<<"$names"
    return 0
}

remove_stack_volumes() {
    local names volumes=() volume
    names=$(get_stack_volumes) || return 1
    [ -z "$names" ] || mapfile -t volumes <<<"$names"
    if [ ${#volumes[@]} -eq 0 ]; then
        err "no volume labelled com.docker.compose.project=$prove_project was found"
        return 1
    fi
    for volume in "${volumes[@]}"; do note "  removing $volume"; done
    docker volume rm "${volumes[@]}" || { err "could not remove the volumes of $prove_project"; return 1; }
}

# get_part_image_name: the first part image in data/media/part_images by name, previews and
# thumbnails left out.
get_part_image_name() {
    local path name
    for path in "$here"/data/media/part_images/*; do
        name=${path##*/}
        [ -f "$path" ] || continue
        [[ $name =~ \.(preview|thumbnail)\. ]] && continue
        echo "$name"
        return 0
    done
    return 1
}

# http_status URL AUTHORIZATION: the HTTP status URL answers with that Authorization header, or 000
# when nothing answered. The header goes through curl's config on stdin, so no secret is on a command line.
http_status() {
    local code
    code=$(printf 'header = "Authorization: %s"\n' "$2" |
        curl --config - -s -o /dev/null -w '%{http_code}' --max-time 30 "$1") || true
    echo "${code:-000}"
}

# get_api_token: an API token of the admin account, signed in with config.env's credentials.
get_api_token() {
    local basic response
    basic=$(printf '%s' "$(config_value INVENTREE_ADMIN_USER):$(config_value INVENTREE_ADMIN_PASSWORD)" | base64 | tr -d '\n')
    response=$(printf 'header = "Authorization: Basic %s"\n' "$basic" |
        curl --config - -fsS --max-time 30 "$prove_image_base_url/api/user/token/") || return 1
    python3 -c 'import json,sys
print(json.load(sys.stdin)["token"])' <<<"$response"
}

# wait_for_api TOKEN: waits until the API answers 200 to the token taken before the delete. 401 or 403
# fails at once: the token row should have come back with the restore, so retrying cannot help.
# Anything else, including a refused connection, means InvenTree is still starting.
wait_for_api() {
    local deadline=$((SECONDS + prove_ready_timeout_minutes * 60)) status
    while [ "$SECONDS" -lt "$deadline" ]; do
        status=$(http_status "$prove_image_base_url/api/user/me/" "Token $1")
        [ "$status" != 200 ] || return 0
        if [ "$status" = 401 ] || [ "$status" = 403 ]; then
            err "the API token taken before the delete was rejected ($status) after the restore"
            return 1
        fi
        sleep 10
    done
    err "InvenTree did not answer for $prove_ready_timeout_minutes minutes"
    return 1
}

write_recovery_hint() {
    err "The volumes were deleted. Recover with: ./docker-compose.sh up"
    err "If that keeps failing: ./docker-compose.sh up --fresh   then   ./docker-compose.sh restore $1"
}

# invoke_prove_data: proves that deleting every volume of the stack loses nothing: dump, count,
# delete, start, count, fetch a part image. DESTRUCTIVE: it deletes the stack's volumes, so run it
# only with the owner's go-ahead. A fresh dump is taken right before the "before" count, so writes
# after an older dump cannot look like a failed restore.
invoke_prove_data() {
    local container image_name token newest before after differences line status_code image_is_served=false
    for container in "$prove_backup_container" "$prove_server_container"; do
        test_container_is_running "$container" || fail "$container is not running; start the stack first"
    done
    image_name=$(get_part_image_name) || fail "no part image in data/media/part_images to fetch"
    token=$(get_api_token) || fail "no API token could be taken from $prove_image_base_url/api/user/token/"

    step "Writing a fresh dump ..."
    invoke_backup
    newest=$(newest_dump "$backups_folder" "$dump_pattern") || fail "data/backups cannot be listed"
    [ -n "$newest" ] || fail "no complete dump exists in data/backups"
    test_dump_is_restorable "$backups_folder/$newest" ||
        fail "$newest cannot be listed by pg_restore or holds no table data; nothing was deleted"

    step "Counting rows before ..."
    before=$(get_inventree_table_counts) || fail "the rows could not be counted; nothing was deleted"
    [ "$(count_lines "$before")" -gt 0 ] || fail "no table was counted; nothing was deleted"
    note "  $(count_lines "$before") tables, dump $newest"

    step "Stopping the stack and deleting its volumes ..."
    if ! invoke_stack down || ! remove_stack_volumes; then write_recovery_hint "$newest"; exit 1; fi

    step "Starting the stack and waiting for the self-restore ..."
    invoke_stack up
    if ! wait_for_api "$token"; then write_recovery_hint "$newest"; exit 1; fi

    step "Counting rows after ..."
    if ! after=$(get_inventree_table_counts); then write_recovery_hint "$newest"; exit 1; fi
    write_uncompared_counts "$before" "$after"
    differences=$(compare_table_counts "$before" "$after" "${prove_uncompared_tables[@]}")
    if [ -n "$differences" ]; then
        while IFS= read -r line; do err "  DIFFERS $line"; done <<<"$differences"
        write_recovery_hint "$newest"
    else
        ok "all $(count_lines "$after") tables match"
    fi

    step "Fetching part image $image_name ..."
    status_code=$(http_status "$prove_image_base_url/media/part_images/$image_name" "Token $token")
    if [ "$status_code" = 200 ]; then
        image_is_served=true
        ok "part image answered 200"
    else
        err "part image answered $status_code"
        [ -n "$differences" ] || err "The image check failed; the data is back."
    fi
    if [ -n "$differences" ] || [ "$image_is_served" != true ]; then exit 1; fi
    ok "every table came back"
}

count_lines() { grep -c . <<<"$1" || true; }
