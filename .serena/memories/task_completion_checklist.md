# Task Completion Checklist

When a coding task is completed, verify the following:

1. **Translations sync**: `strings.json` and `translations/en.json` must have identical content
2. **No unused imports**: Check all modified files
3. **Error handling**: Any new service calls wrapped in `try/except HomeAssistantError`
4. **Config merging**: If config keys changed, verify coordinator reads from merged `{**data, **options}`
5. **HVACMode enums**: No raw string mode values (use `HVACMode.HEAT`, not `"heat"`)
6. **Constant centralization**: New constants go in `const.py`, not inline
7. **Service definitions**: If new services added, update `services.yaml`
8. **Lint check**: Run `ruff check custom_components/room_climate/`
9. **Setpoint dedup**: If calibration logic changed, verify `_last_applied_setpoint` guard still works
10. **README**: Update if user-visible behavior changed
