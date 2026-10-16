# Usage

To use care_token_display in a project:

```python
import token_display
```

## Audio announcements

The display calls out new tokens with a chime followed by a pre-recorded voice
prompt that spells the token code one character at a time. Audio is assembled
**in the browser** using the Web Audio API from a flat folder of small WAV
fragments shipped with the plugin — no server-side TTS, no extra dependencies,
and no `SpeechSynthesis` (which is unreliable on signage hardware such as
Samsung Tizen / MagicINFO).

A typical announcement plays as:

> *(chime)* "Now serving token, G, zero, zero, one"

The "Now serving token" prefix can be played in multiple languages back to
back for the same token — see [Multi-language announcements](#multi-language-announcements).
Tokens are deduplicated client-side via `localStorage`, so a given token is
announced at most once per display across page refreshes.

### Query parameters

| Param     | Default                   | Description                                                                                                                                                                       |
| --------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `va_lang` | `VA_DEFAULT_LANG` setting | Comma-separated language codes for the prefix announcement (e.g. `en_IN`, `ml_IN,en_IN`). Each code must have a matching `prefix-<code>.wav`. Pass `?va_lang=` (empty) to mute. |
| `show_breaks` | `SHOW_INACTIVE_AS_BREAK` setting | `1` shows inactive service points as "On break"; `0` hides them. See [Board states](#board-states). |

### Muting the voice announcer

The voice announcer is muted by resolving to an empty list of languages. Two
ways to do this:

- Per-request: pass `?va_lang=` with no value (or only invalid codes).
- Globally: configure `VA_DEFAULT_LANG = []` in your plugin settings.

When muted, the page is rendered without the announcer payload or script —
no `localStorage` writes, no fragment fetches — and a plain
`<meta http-equiv="refresh">` drives the periodic reload.

### Multi-language announcements

The chime is language-neutral and reused as-is. Everything else — the
*"Now serving token"* prefix and the per-character utterances — is recorded
per language under a `<lang>/` subdirectory (for example `en_IN/prefix.wav`,
`en_IN/A.wav`, `ml_IN/prefix.wav`, `ml_IN/A.wav`).

The playback order is controlled by:

1. The `?va_lang=` query parameter, if present (comma-separated, e.g.
   `?va_lang=ml_IN,en_IN`).
2. Otherwise, the `VA_DEFAULT_LANG` plugin setting (default: `["en_IN"]`).

For each token, the announcer schedules every configured language pass
back-to-back with a 1-second pause between languages:

```
[chime] [ml_IN/prefix] [ml_IN/G] [ml_IN/0] [ml_IN/0] [ml_IN/1]
  ... 1 second pause ...
[chime] [en_IN/prefix] [en_IN/G] [en_IN/0] [en_IN/0] [en_IN/1]
```

See [Muting the voice announcer](#muting-the-voice-announcer) for how to
disable playback.

### Audio fragments

The fragments live under
`src/token_display/static/token_display/sounds/`:

| File                                | Contents                                                        |
| ----------------------------------- | --------------------------------------------------------------- |
| `chime.wav`                         | Two-tone leading chime (language-neutral).                      |
| `<lang>/prefix.wav`                 | "Now serving token" recorded in `<lang>` (e.g. `en_IN/prefix.wav`). |
| `<lang>/A.wav` … `<lang>/Z.wav`     | Each English letter pronounced in `<lang>`.                     |
| `<lang>/0.wav` … `<lang>/9.wav`     | Each digit pronounced in `<lang>`.                              |

So a configuration with `VA_DEFAULT_LANG = ["en_IN", "ml_IN"]` requires the
`en_IN/` and `ml_IN/` subdirectories to each contain `prefix.wav`, `A.wav` …
`Z.wav` and `0.wav` … `9.wav`. `chime.wav` is shared.

All files must share the same sample format (the bundled placeholders are
22.05 kHz mono 16-bit PCM, but the Web Audio API will resample anything it
can decode). Each fragment should bake in a short trailing pause (~120 ms) so
that consecutive characters do not slur together when concatenated.

### Replacing the placeholder voice

The shipped fragments are auto-generated placeholders using macOS's `say`
utility (or stdlib tones on other platforms). To swap in real recordings:

1. Record one WAV per fragment using the same filenames as above.
2. Use a single voice talent and a consistent peak level (~ -3 dBFS).
3. Trim leading silence aggressively; leave ~120 ms of trailing silence.
4. Drop the new files into
   `src/token_display/static/token_display/sounds/` — no code changes needed.

To regenerate the placeholders at any time, run:

```sh
python scripts/generate_placeholder_fragments.py
```

### Kiosk setup

Most browsers block autoplay until the user interacts with the page. For an
unattended kiosk, launch Chromium with:

```shell
chromium --kiosk \
  --autoplay-policy=no-user-gesture-required \
  "https://<your-care-host>/token_display/sub_queues/<sub_queue_external_ids>/?token=<api_token>"
```

If the display is opened in a normal browser tab, click anywhere on the page
once after loading to unlock audio.

### Graceful degradation

- If the Web Audio API is unavailable, the page renders silently and the
  currently shown tokens are recorded as "announced" so they do not loop on
  every refresh.
- If a fragment fails to load or decode, the announcement is aborted, the
  affected tokens are still marked as announced, and the page reloads on
  schedule.
- The `<meta http-equiv="refresh">` fallback still works with JavaScript
  disabled — the page refreshes on schedule but plays no audio.

## Board states

Each row on the board shows the state of its counter / room as a short text
line above the token. The board's colours and backgrounds stay the same in
every state.

| State | When | Shown as |
| --- | --- | --- |
| Now calling | Token called to the counter / room (status `CREATED` with a sub-queue): stays until the patient arrives | "Now calling" above the token |
| In consultation | Token being served (status `IN_PROGRESS`) | "In consultation" above the token |
| Emergency | Token category has `metadata.priority = true`, or its name contains Emergency / Priority / Urgent | "Emergency" above the token |
| On break | Sub-queue (service point) status is `inactive`, **only when breaks are enabled** (below) | "On break" in place of the token |

"Next" lists tokens still waiting in the queue (not yet called to any
counter), priority tokens first.

Tokens marked "awaiting re-call" today for the resources on the board are
listed in a **Missed** strip at the bottom, newest first, up to
`MISSED_TOKENS_LIMIT` (default `8`; `0` hides the strip).

### Showing breaks

By default an inactive service point is hidden from the board, as before.
Marking a service point inactive does not by itself mean a break, so showing
it as "On break" is an explicit choice:

- For every board: set `SHOW_INACTIVE_AS_BREAK = True` in the plugin settings.
- For one board: add `?show_breaks=1` to its URL (`?show_breaks=0` turns it
  off when the setting is on).

### What is announced, and when

| On the board | Announcement | Said again when |
| --- | --- | --- |
| A patient is called to a room ("Now calling") | chime, *"Now serving token"* + the token, in each `va_lang` | the same patient is called again (re-call), or the room is back from a break with the patient still called |
| A room goes on break ("On break") | chime, *"The doctor is on a short break, please wait"* (`<lang>/on_break.wav`) | the room goes on break again |
| A patient shown for the first time already in consultation | chime, *"Now serving token"* + the token | — |

A called patient walking in (called → in consultation) is not announced again,
and a plain page refresh never repeats an announcement.

The `on_break.wav` files are generated with a neural text-to-speech voice
(Kokoro, Hindi female voice `hf_beta`, slightly brighter with a soft reverb, for `hi_IN` and `en_IN`; espeak-ng for
`ml_IN`). To use a human recording instead, record the sentence in each language and replace
`sounds/<lang>/on_break.wav` (WAV, mono, 44.1 kHz, 16-bit):

- `hi_IN`: "कृपया ध्यान दें। डॉक्टर थोड़ी देर के लिए ब्रेक पर हैं। कृपया प्रतीक्षा करें।"
- `en_IN`: "Attention please. The doctor is on a short break. Please wait."
- `ml_IN`: "ശ്രദ്ധിക്കുക. ഡോക്ടർ അല്പസമയം ഇടവേളയിലാണ്. ദയവായി കാത്തിരിക്കുക."
