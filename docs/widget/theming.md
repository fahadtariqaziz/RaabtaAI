# Widget theming reference

Theme comes from the institution's `settings.widget` (set in the admin panel) and is returned by
`GET /api/v1/widget/config/{slug}`. Snippet `data-*` attributes override it per page.

| Setting (`settings.widget.*`) | Type | Effect | Default |
|---|---|---|---|
| `primary_color` | `#rrggbb` | launcher, header, your-message bubbles, buttons | school `#0f766e`, college `#1d4ed8`, university `#7c3aed` |
| `position` | `left` \| `right` | launcher corner | `right` |
| `welcome` | `{en, ur, roman_ur}` | first bubble | "Assalam-o-Alaikum! Ask me anything about … at {name}." |
| `suggested_questions` | `{en: [...], ur: [...], roman_ur: [...]}` | 3 starter buttons per language | by institution type |
| `whatsapp_number` | E.164 digits, e.g. `923001234567` | shows "Continue on WhatsApp" (`wa.me` link with a session code) | hidden |
| `allowed_origins` | list of `https://host[:port]` | which sites may open chat sessions | none (localhost only in dev) |

Languages offered in the toggle = the institution's `languages`. Urdu switches the panel to RTL
and lazy-loads *Noto Nastaliq Urdu*.

## CSS variables (inside the shadow root)

| Variable | Meaning |
|---|---|
| `--p` | primary colour (from `primary_color` / `data-primary`) |
| `--fg`, `--mut` | text / muted text |
| `--bg`, `--bub`, `--bd` | panel background / assistant bubble / borders |

Host-page CSS cannot reach these (Shadow DOM); colours are deliberately limited to one brand
colour so contrast stays readable. On screens ≤ 480 px the panel opens full-screen.
