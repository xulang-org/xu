# Screen events and appearance

`ActionDispatcher` owns a typed function table. Create it with
`action_dispatcher(&model, &screen)`; these arguments select types and are never
retained. Pass context and target as exclusive borrows for each dispatch.
The target type is inferred: retained `View` loops and standalone control state
use the same factory and registration rules.

```xu
fn save(model $&Model,screen $&widgets.Screen,action &widgets.Action) string {
    model.saved = true
    screen.set_text(model.status,"Saved") or (err) { << err.msg() }
    << ""
}

$actions := widgets.action_dispatcher(&model,&screen)
actions.on(save_button,widgets.ACTION_ACTIVATE,save) or >>
actions.on_any(other_control,inspect) or >>
handled := actions.dispatch(&action,$&model,$&screen) or >>
```

Handlers return `""` on success or an error message. Catch errors inside the
handler: Xu function values do not carry the inferred throw ABI of a named
function. The dispatcher propagates a returned error and never invokes fallback
after a failed handler. Register named functions that do not retain Screen or
context borrows. `ActionDispatcher#Context,Screen,Action` is the explicit type;
normal registration and dispatch infer all type arguments.

IDs must be positive signed 32-bit values. `on` accepts the exported semantic
`ACTION_*` kinds, excluding `ACTION_NONE`. Invalid registrations throw; dispatch
of an invalid action returns false. Re-registering a key replaces its function.
An exact `(id,kind)` match runs once before considering `on_any(id)`. The wildcard
receives semantic actions only, never repaint-only `ACTION_NONE` signals.
Keys use strings so large IDs cannot overflow when encoding an action kind.

`dispatch` returns false for a miss. `set_fallback(handler)` installs one optional
fallback and replaces the previous one; `clear_fallback()` removes it.
`dispatch_or_fallback` tries dispatch first and reports whether either ran.

Existing `run_screen($&screen,events,$&model)` callers keep their
`ScreenHandler.layout/update` behavior. Pass a fourth, owning dispatcher argument
to run registered functions first; unmatched actions reach the optional table
fallback, then legacy `update`. At most one table is accepted. For applications
without `update`, use
`run_screen_actions($&screen,events,$&model,layout_handler,&actions)`;
the layout callback also returns an empty string or error message. Both entries
dispose the Screen on close and callback failure. Custom loops call
`dispatch_or_fallback` for actions from both `event` and `take_actions`.

`Appearance` is a separate type in `screen_style_sheet.xu`, with no callbacks:

```xu
styles := widgets.dark_styles()
appearance := widgets.screen_appearance(&styles,true) or >>
screen.apply_appearance(&appearance) or >>
```

Applying appearance validates and copies style tokens, updates reduced motion,
and invalidates paint. It does not dispatch events. Keep theme, density, text
scale and motion configuration in the style path. Handlers change business
state/control values and request an appearance pass when necessary.

Run `XU=./bin/xu python3 scripts/ui_action_dispatcher_smoke.py` from the Xu root
for dispatcher, invalid-input, fallback, callback-error and appearance assertions.
