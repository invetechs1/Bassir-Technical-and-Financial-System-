# Frontend structure — نظام بصير للعروض الفنية والمالية

## What changed (Phase 1 — modularization)

`app/static/app.js` (1,799 lines) is now split into 21 ordered modules with **zero
behavior change** (the concatenation of the modules is byte-identical to the original
file, verified at split time):

```
app/static/
├── index.html        # markup + <link>/<script> tags
├── styles.css
├── i18n.js           # translation dictionary (unchanged)
└── js/               # classic scripts, loaded in order (shared global scope)
    ├── 00-core.js            # $, api(), toast, helpers
    ├── 01-roles-tenant.js    # ME, loadMe, company switcher, brand
    ├── 02-nav.js             # go(), nav counts
    ├── 03-dashboard.js
    ├── 04-new-proposal.js    # generate flow + upload
    ├── 05-proposals-list.js
    ├── 06-viewer-boq.js      # proposal viewer + BoQ editing/sub-items
    ├── 07-prices.js
    ├── 08-library.js
    ├── 09-etimad.js
    ├── 10-style-engine.js    # technical repo + style bar
    ├── 11-tenants-users.js   # members, roles, contact, logo
    ├── 12-forsah.js
    ├── 13-repo.js            # knowledge repository
    ├── 14-opportunity.js
    ├── 15-docs.js
    ├── 16-analytics.js
    ├── 17-settings.js        # incl. notification channels
    ├── 18-execution.js       # daily productivity, subcontractors, profitability
    ├── 19-notifications.js   # bell + polling
    └── 20-boot.js            # bootstrap
```

## Rules

- **Load order matters** — files share one global scope and are loaded in numbered
  order from `index.html`. Top-level code may only use what earlier modules define;
  event handlers and functions can reference anything.
- New feature → new numbered module (or extend the matching one) + its `<script src>`
  tag in `index.html`.
- `scripts/system_check.py` includes checks that the modules are served.

## Phase 2 (optional, when committing long-term)

Next step when desired: a Vite build migrating module-by-module to ES modules and
components. Each file above maps naturally to one future component/store. Migrate
incrementally per page, keeping `python scripts/system_check.py` green at every step.
