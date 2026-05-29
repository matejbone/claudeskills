---
name: ui-ux-pro-max
description: "UI/UX design intelligence for web and mobile. Use whenever a task involves UI structure, visual design decisions, interaction patterns, or UX quality. Triggers: build/design/create/implement/review/fix/improve/optimize any UI — landing page, dashboard, admin panel, SaaS, portfolio, blog, mobile app, button, modal, navbar, form, chart, card, table. Covers 67 styles (glassmorphism, claymorphism, brutalism, neumorphism, bento grid, dark mode, minimalism), 161 color palettes, 57 font pairings, 99 UX guidelines, and 15 tech stacks."
---

# UI/UX Pro Max — Design Intelligence

Comprehensive design guide for web and mobile. Searchable database with BM25-ranked recommendations across 67 styles, 161 color palettes, 57 font pairings, 161 product types with reasoning rules, 99 UX guidelines, and 25 chart types.

## When to Use

**Must use:** designing new pages, creating/refactoring UI components, choosing color/typography/layout systems, reviewing UI code for accessibility or visual consistency, implementing navigation/animation/responsive behavior.

**Skip:** pure backend logic, API/DB design, infrastructure, non-visual scripts.

**Decision rule:** if the task changes how a feature looks, feels, moves, or is interacted with → use this skill.

---

## Priority Rule Table

| Priority | Category | Impact | Domain | Key Checks | Anti-Patterns |
|---|---|---|---|---|---|
| 1 | Accessibility | CRITICAL | `ux` | Contrast 4.5:1, alt text, keyboard nav, aria-labels | Removing focus rings, icon-only buttons without labels |
| 2 | Touch & Interaction | CRITICAL | `ux` | Min 44×44px tap targets, 8px+ spacing, loading feedback | Hover-only interactions, instant state changes (0ms) |
| 3 | Performance | HIGH | `ux` | WebP/AVIF, lazy loading, CLS < 0.1 | Layout thrashing, cumulative layout shift |
| 4 | Style Selection | HIGH | `style`, `product` | Match product type, consistency, SVG icons (no emoji) | Mixing flat & skeuomorphic, emoji as icons |
| 5 | Layout & Responsive | HIGH | `ux` | Mobile-first, viewport meta, no horizontal scroll | Fixed px containers, disabling zoom |
| 6 | Typography & Color | MEDIUM | `typography`, `color` | Base 16px, line-height 1.5, semantic color tokens | Body text < 12px, gray-on-gray, raw hex in components |
| 7 | Animation | MEDIUM | `ux` | Duration 150–300ms, spatial continuity, reduced-motion | Decorative-only animation, animating width/height |
| 8 | Forms & Feedback | MEDIUM | `ux` | Visible labels, error near field, progressive disclosure | Placeholder-only labels, errors only at page top |
| 9 | Navigation | HIGH | `ux` | Predictable back, bottom nav ≤ 5, deep linking | Overloaded nav, broken back behavior |
| 10 | Charts & Data | LOW | `chart` | Legends, tooltips, accessible colors | Conveying meaning by color alone |

---

## Step 1 — Generate Design System (Always First)

Before writing any code, generate a complete design system recommendation. The reasoning engine analyzes the product type and returns pattern + style + colors + typography + anti-patterns:

```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<product description>" --design-system -p "<Project Name>"
```

**Examples:**
```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "fintech banking app" --design-system -p "MyBank"
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "beauty spa wellness" --design-system -p "Serenity Spa"
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "SaaS dashboard analytics" --design-system -p "DataDash"
```

The output includes:
- **Pattern** — recommended landing page/app structure
- **Style** — best matching UI style with rationale
- **Colors** — primary, secondary, CTA, background, text hex values
- **Typography** — heading + body font pairing with Google Fonts URL
- **Key Effects** — animations and interactions
- **Anti-Patterns** — what NOT to do for this industry
- **Pre-delivery Checklist** — common pitfalls to verify before shipping

### Persist to Files (for multi-session projects)

```bash
# Save global design system as MASTER.md
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "SaaS dashboard" --design-system --persist -p "MyApp"

# Also create a page-specific override
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "SaaS dashboard" --design-system --persist -p "MyApp" --page "dashboard"
```

Creates:
```
design-system/myapp/
├── MASTER.md           # Global source of truth
└── pages/
    └── dashboard.md    # Page-specific overrides
```

When building a page: check `pages/<page>.md` first; its rules override MASTER. If not found, use MASTER exclusively.

---

## Step 2 — Query Specific Domains

After generating the design system, use domain-specific searches for detail:

```bash
# Style details
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "glassmorphism" --domain style

# Color palette for product type
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "healthcare medical" --domain color

# Typography pairing
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "elegant serif luxury" --domain typography

# Chart recommendations for data type
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "time series revenue trend" --domain chart

# Landing page pattern
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "lead generation conversion" --domain landing

# UX guidelines for a topic
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "form validation error handling" --domain ux

# Stack-specific guidelines
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "responsive layout" --stack react
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "form validation" --stack nextjs
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "animation performance" --stack html-tailwind
```

Available domains: `style`, `color`, `chart`, `landing`, `product`, `ux`, `typography`, `google-fonts`, `icons`, `react`, `web`

Available stacks: `react`, `nextjs`, `vue`, `nuxtjs`, `nuxt-ui`, `svelte`, `astro`, `angular`, `laravel`, `html-tailwind`, `shadcn`, `swiftui`, `react-native`, `flutter`, `jetpack-compose`, `threejs`

---

## Step 3 — Apply Design Intelligence

Use the design system output to guide code generation. Apply these universal rules:

### Typography
- Minimum body text: 16px (never below 12px)
- Line-height: 1.5 for body, 1.2–1.3 for headings
- Maximum line width: 65–75ch for reading comfort
- Use semantic type scale, not raw sizes

### Color
- Define CSS custom properties: `--color-primary`, `--color-secondary`, `--color-accent`, `--color-bg`, `--color-text`
- Never hardcode hex values in components — always use tokens
- Minimum contrast: 4.5:1 for normal text, 3:1 for large text (WCAG AA)
- Don't convey meaning through color alone; always add icon or text

### Spacing
- Use 4pt/8dp incremental spacing scale
- Minimum touch target: 44×44px (iOS HIG) / 48×48dp (Material)
- Minimum gap between touch targets: 8px

### Animation
- Duration: 150–300ms for UI transitions; 300–500ms for page transitions
- Always include `prefers-reduced-motion` media query
- Prefer `transform` and `opacity` over properties that trigger layout

### Icons
- Always use SVG icon libraries (Heroicons, Lucide, Phosphor)
- Never use emoji as icons
- Icon-only buttons must have `aria-label`

---

## Pre-Delivery Checklist

Before finalizing any UI, verify:

- [ ] No emoji used as icons (SVG only: Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150–300ms)
- [ ] Text contrast ≥ 4.5:1 in light mode
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive tested at: 375px, 768px, 1024px, 1440px
- [ ] No horizontal scroll on any breakpoint
- [ ] Loading states for async actions
- [ ] Error states with messages near the affected field
- [ ] Empty states defined (not just blank space)

---

## Supported Stacks

| Category | Stacks |
|---|---|
| Web (HTML) | HTML + Tailwind (default) |
| React | React, Next.js, shadcn/ui |
| Vue | Vue, Nuxt.js, Nuxt UI |
| Angular | Angular |
| PHP | Laravel |
| Other Web | Svelte, Astro, Three.js |
| iOS | SwiftUI |
| Android | Jetpack Compose |
| Cross-platform | React Native, Flutter |
