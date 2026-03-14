# Suggested Commands

## System (Windows)
- `Get-ChildItem -Recurse -File` — list all files
- `Select-String -Pattern "text" -Path "*.py" -Recurse` — search in files (PowerShell grep)

## Development
This is a Home Assistant custom integration — there is no standalone dev server.
To test, copy `custom_components/room_climate/` to your HA instance's `custom_components/` directory
and restart Home Assistant.

## Validation
- **Linting**: `ruff check custom_components/room_climate/`
- **Formatting**: `ruff format custom_components/room_climate/`
- **Type checking**: `mypy custom_components/room_climate/`
- **HA validation**: Use `hass --script check_config` on the HA instance

## Git
- `git init` — initialize repo
- `git add . && git commit -m "message"` — stage and commit
- `git remote add origin <url> && git push -u origin main` — push to GitHub
- `git tag v1.0.0 && git push --tags` — tag a release for HACS

## HACS Deployment
1. Push to GitHub with the `custom_components/room_climate/` structure
2. Create a GitHub release tagged `v1.0.0`
3. Users add the repo URL as a custom HACS repository (category: Integration)
