# Rules

The non-negotiables a diagram cannot show. A pull request that breaks one
is reported, never quietly accepted.

- The timer engine owns the clock. No view starts, stops or computes time.
- The view imports the engine. The engine imports nothing from the app.
- Settings are read once at launch and passed in. Nothing reads
  UserDefaults during a countdown.
