[InvenTree](https://github.com/inventree/InvenTree) in Docker, served over
[Tailscale](https://tailscale.com/) with real HTTPS to every device on your tailnet, plus a catalog
tool that keeps the inventory declared in TOML files and prints QR labels on A4 sticker sheets.

## Stack

| service | image | role |
| --- | --- | --- |
| `tailscale` | `tailscale/tailscale:v1.102.4` | joins your tailnet as `inventree` and forwards `:443` |
| `gateway` | `caddy:2.11.4-alpine` | HTTPS for the `ts.net` name with certificates from Tailscale; serves static and media files |
| `server` | `inventree/inventree:1.5.6` | the app and its REST API, at `https://inventree.<tailnet>.ts.net` |
| `worker` | `inventree/inventree:1.5.6` | InvenTree's background tasks |
| `db` | `postgres:17.10-alpine` | the database |
| `db-backup` | `postgres:17.10-alpine` | hourly database dumps into `data/backups` |

Every image is pinned to a version. Migrations run when the server starts on a new version.

## Quick start

Requires [Docker](https://docs.docker.com/get-docker/), PowerShell (built into Windows; `pwsh`
elsewhere) and a Tailscale account with
[HTTPS certificates](https://tailscale.com/kb/1153/enabling-https) enabled.

```powershell
git clone --recursive https://github.com/intisy-compose/inventree-compose
cd inventree-compose

.\docker-compose.ps1 init-config   # creates config.env and generates the passwords
# put an auth key from https://login.tailscale.com/admin/settings/keys into TS_AUTHKEY in config.env
.\docker-compose.ps1 up            # the one CLI; run it without a known command to list them all
```

`up` joins the tailnet first, reads the node's real `ts.net` name and writes `INVENTREE_HOST` into
`config.env` before starting the rest, then prints the URL. Sign in with `INVENTREE_ADMIN_USER` and
the generated `INVENTREE_ADMIN_PASSWORD`. The auth key is only used for the first join; the node
identity stays in `data/tailscale` afterwards.

## Catalog

The catalog tool drives InvenTree through its REST API from declared files, so the structure cannot
drift into "Electronics" and half a dozen spellings of the same thing:

- `data/catalog.toml` declares every category, field (a parameter template, with its type, options
  and categories), tag, location and model (a part, with its specs and product image).
- `catalog sync` makes InvenTree match it and uploads the part images; `catalog check` lists every
  difference.
- `catalog add <batch.toml>` and `update <batch.toml>` create or change assets: serialized stock
  items whose serial number is the asset ID (`SAM-0001`). The whole batch is validated before
  anything is written. A part inside a computer or enclosure is installed in that item.
- Each asset carries its label size as a tag: large (QR code, ID and name), standard (QR code and
  ID), small (ID only) or none. Labels are printed from InvenTree itself (below).
- `scripts/import_shelf.py` moved an inventory over from
  [shelf-compose](https://github.com/intisy-compose/shelf-compose), keeping every asset ID.

It needs Python 3.11 or newer on the host, with [Pillow](https://pypi.org/project/pillow/) for
images. The public data template ships a
starter `catalog.toml`; `CATALOG.md` in a data repo documents the rules.

## Dashboard

`plugins/inventory_dashboard` is a small InvenTree plugin, mounted into the server, with five
dashboard widgets for this kind of inventory: an overview with value by category, what needs
attention (untested, faulty, broken), the machines with their installed parts, the newest assets,
and how many stickers of each size there are. `catalog sync`
activates it; add the widgets from the dashboard menu.

## Printing labels from InvenTree

`plugins/asset_labels` is a label printer plugin, the only way labels are printed: select stock
items in InvenTree (by category, location, search or one by one), choose Print labels, the `Asset
labels` template and the `Asset labels` printer, pick the sticker paper (full A4 sticker sheets by
default, or A4 CD label sheets with labels around the rings, in the centre discs and around them),
and the PDF downloads. With "Outline groups" every location and machine gets a name tag and a
nested outline, continued across pages. `catalog
sync` activates both plugins and creates the template.

## Data and backups

The database and InvenTree's uploaded files live in the Docker volumes `inventree_inventree-db` and
`inventree_inventree-files`, because Postgres on a Windows bind mount fails on file permissions.
`db-backup` dumps the database every hour into `data/backups` and keeps the newest `BACKUP_KEEP`
(48). `.\docker-compose.ps1 backup` takes one now and `restore [file]` puts one back (the newest by
default). Part images come back with `catalog images`.

`data/` is a git submodule. The public template is the default; point it at your own repo with
`.\docker-compose.ps1 data use <owner/repo[@ref]>`.
