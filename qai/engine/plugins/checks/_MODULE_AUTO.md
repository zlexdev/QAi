# checks/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

> Importing this subpackage registers every built-in check as a side effect — same

## __init__.py
```
# Importing this subpackage registers every built-in check as a side effect — same


```

## security_headers.py
```
# First passive check — inspects already-captured response headers for a missing

_REQUIRED_HEADERS = …

cls SecurityHeadersCheck(Check)
  async run(ctx: CheckContext, replay: object? = None) -> list[PluginFinding]

```
