# Installing the RaabtaAI chat widget

The widget is one `<script>` tag. It renders inside a Shadow DOM, so your site's CSS cannot
break it and it cannot break your site. Bundle size ≈ 8 KB gzipped, no dependencies.

## 1. Get your snippet

Admin panel → **Settings → Website widget** (or `GET /api/v1/institution/widget-snippet`).
It looks like this:

```html
<script src="https://cdn.raabta.ai/widget/v1/widget.js" data-institution="abc-grammar-school" async></script>
```

## 2. Allow your website's address

The widget only works on origins you allow (e.g. `https://abcgrammar.edu.pk` and
`https://www.abcgrammar.edu.pk` — these are **different** origins; add both if both are used).
Ask your RaabtaAI contact or set it in **Settings → Website widget → Allowed websites**
(stored as `settings.widget.allowed_origins`). Pages on other origins get no chat session.

## 3. Paste the snippet

Put it just before `</body>` on every page where the chat should appear.

### WordPress
- **Plugin way (recommended):** install *WPCode* (or *Insert Headers and Footers*) → *Code
  Snippets → Header & Footer* → paste into **Footer** → Save.
- **Theme way:** *Appearance → Theme File Editor → footer.php* → paste before `</body>`.
  (Theme updates may remove it; prefer the plugin.)
- Caching/optimisation plugins (WP Rocket, Autoptimize, LiteSpeed): exclude `widget.js` from
  "combine/defer JS" if the launcher does not appear.

### Wix
*Settings → Custom Code → + Add Custom Code* → paste → **Add Code to Pages: All pages** →
**Place Code in: Body – end** → Apply. (Needs a Premium plan with a connected domain.)

### Custom HTML / other builders (Squarespace, Webflow, Blogger)
Use the site-wide "footer code injection" setting, or paste before `</body>` in your template.

## Optional attributes

| Attribute | Values | Default |
|---|---|---|
| `data-lang` | `en`, `ur`, `roman_ur` | Roman Urdu if enabled, else first language |
| `data-position` | `left`, `right` | `right` (from settings) |
| `data-primary` | `#rrggbb` | your theme colour from settings |
| `data-open` | (present) | panel closed until clicked |

## Content-Security-Policy (only if your site sets a CSP)

```
script-src  https://cdn.raabta.ai;
connect-src https://api.raabta.ai;
style-src   https://fonts.googleapis.com;      # Urdu font, loaded only when Urdu is chosen
font-src    https://fonts.gstatic.com;
```

The widget uses no `eval`, no inline `<script>`, and no cookies. It stores only a random visitor
id and a 24-hour session token in `localStorage`; the visible chat is kept in `sessionStorage`
for the current tab.

## Checking it works

1. Open your site → the round chat button appears bottom-right (bottom-left if configured).
2. Ask "What is the fee for Class 3?" → you see a status line ("Checking the fee table…"), then
   the answer with a **Source** chip.
3. Nothing appears? Open the browser console: a `403` on `/widget/sessions` means the page's
   origin is not in the allowed list; a `404` on `/widget/config/…` means the `data-institution`
   slug is wrong or the account is suspended.
