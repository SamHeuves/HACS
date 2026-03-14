# Code Style & Conventions

## Python
- Python 3.12+ with `from __future__ import annotations`
- Type hints on all function signatures and class attributes
- `str | None` union syntax (not `Optional[str]`)

## Home Assistant Patterns
- Use `HVACMode` enum from `homeassistant.components.climate`, never raw mode strings
- All user-facing text in `strings.json` + `translations/en.json` — never hardcoded in Python
- Use `selector.SelectSelectorConfig(translation_key=...)` for translatable select options
- Options flow: access `self.config_entry` (HA-provided), no constructor parameter
- Optional config fields: use `user_input.get(KEY)` in options flow so clearing sets to `None`
- Wrap all device service calls in `try/except HomeAssistantError`
- Use atomic service calls: `climate.set_temperature` with `hvac_mode` param
- Config merging: `{**entry.data, **entry.options}`

## Naming
- Constants: `UPPER_SNAKE_CASE`
- Classes: `PascalCase` (e.g., `RoomClimateCoordinator`)
- Functions/methods: `snake_case`
- HA async methods: `async_` prefix
- HA callback methods: `@callback` decorator

## Docstrings
- Module-level docstring on every `.py` file
- Class docstrings for entities and coordinator
- Method docstrings for non-trivial public methods
- No redundant comments that just narrate what the code does

## File Organization
- `const.py` for all constants — no constants scattered in other files
- Coordinator logic in `__init__.py`, entity logic in respective platform files
- Service registration in platform `async_setup_entry`
