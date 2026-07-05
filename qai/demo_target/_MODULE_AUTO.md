# demo_target/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

## app.py
```
# Self-contained FastAPI fixture with one signup form — the ONE-question demo target.

_FORM_HTML = …

async index() -> str

async signup(name: str = Form(...), email: str = Form(...), age: str = Form('')) -> dict[str, object]

```
