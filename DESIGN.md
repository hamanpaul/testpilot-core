# Design System Inspired by Arcadyan

## 1. Visual Theme & Atmosphere

Arcadyan's product UI should feel like a broadband control plane built by an OEM with strong hardware roots: precise, bilingual, modular, and quietly technical. The public brand contributes a light workspace, charcoal chrome, and a distinctive lime green (`#99CC00`) accent; the corporate presentation template adds chapter-like dividers, boxed content rhythm, and a clear sense of section hierarchy. The result is not a consumer marketing aesthetic. It is an operator-facing, support-facing interface where density is allowed, but disorder is not.

The default environment is light-first: white and soft gray data surfaces (`#FFFFFF`, `#F1F3F4`) carry the bulk of tables, settings, and diagnostics, while darker graphite surfaces (`#3C4043`, `#3C3D41`) are reserved for global navigation, monitoring overlays, log consoles, and dark-mode variants. Arcadyan Green is used as a signal, not a blanket. It should mark active states, section keylines, confirmation actions, and high-confidence status, but it should never flood an entire screen.

Typography follows the same split between precision and readability. `Montserrat` carries Latin headings, labels, and UI controls with a clean engineered tone; `Noto Sans TC` handles Traditional Chinese without visual mismatch; monospaced fallbacks are reserved for CLI, logs, firmware versions, and telemetry. Screens should feel globally deployable and bilingual by default, with aligned numbers, disciplined spacing, and restrained motion.

**Key Characteristics:**
- Light-first enterprise workspace with dark graphite system chrome
- Arcadyan Green (`#99CC00`) as a precise accent for activation, validation, and section marking
- `Montserrat` + `Noto Sans TC` bilingual typography with tabular numerals for data
- PPT-inspired chapter rhythm translated into green keylines, modular panels, and clear section breaks
- Compact 4-8px radius geometry; pills only for chips, segmented filters, and tiny status elements
- Data-dense modules, quiet cards, and highly legible tables for broadband / Wi-Fi / CPE workflows
- Dark variant optimized for logs, monitoring, diagnostics, and NOC-like contexts
- Motion is minimal and purposeful: hover emphasis, focus clarity, and state change only

## 2. Color Palette & Roles

### Primary Brand
- **Arcadyan Green** (`#99CC00`): Primary brand accent. Use for active navigation markers, primary confirmation actions, selected states, and section keylines.
- **Pure White** (`#FFFFFF`): Main workspace background, card surface, form background.
- **Graphite 800** (`#3C4043`): Dark navigation chrome, secondary dark surfaces, dark buttons.
- **Graphite 900** (`#3C3D41`): Global dark background, monitoring overlays, dark-mode canvas.

### Neutral Workspace
- **Gray 050** (`#F1F3F4`): Secondary page surface, table headers, neutral filter bands.
- **Gray 100** (`#DADCE0`): Borders, dividers, quiet panel outlines, inactive control edges.
- **Gray 300** (`#979797`): Dashed dividers, disabled strokes, tertiary separators.
- **Gray 500** (`#666666`): Default body text, long descriptions, helper copy.
- **Gray 600** (`#5F6368`): Secondary labels, metadata, muted navigation text.

### Interactive
- **Green Hover** (`#A8D426`): Hover state for primary green actions.
- **Green Active** (`#ADD633`): Pressed state for primary green actions.
- **Dark Action** (`#3C4043`): Secondary system action background.
- **Dark Action Hover** (`#595D5F`): Hover state for graphite actions.
- **Focus Ring** (`rgba(153, 204, 0, 0.25)`): Keyboard focus halo around interactive controls.

### Status & Semantic
- **Info Blue** (`#00ADDC`): Informational links, informational chips, secondary chart emphasis.
- **Success Teal** (`#1AB39F`): Success, healthy system indicators, completed states.
- **Warning Amber** (`#FEB80A`): Warnings, maintenance, degraded service states.
- **Error Red** (`#DC3545`): Error, critical alerts, destructive actions.
- **Periwinkle** (`#738AC8`): Secondary comparison state, alternate series in analytics views.

### Data Visualization Accent Set
- **Lime** (`#7FD13B`): Primary metric / throughput / healthy service series.
- **Magenta** (`#EA157A`): Anomaly or contrast series in charts only.
- **Amber** (`#FEB80A`): Warning series, threshold bands.
- **Cyan** (`#00ADDC`): Secondary data line, network info signals.
- **Periwinkle** (`#738AC8`): Comparison or historical baseline.
- **Teal** (`#1AB39F`): Positive delta, stability trend, validation pass.

### Dark Variant
- **Dark Background** (`#3C3D41`): Dark-mode page canvas, monitoring backdrop.
- **Dark Surface** (`#3C4043`): Cards, drawers, side panels in dark mode.
- **Dark Border** (`#5F6368`): Dark-mode separators and control outlines.
- **Dark Text Primary** (`#DADCE0`): Main text on dark surfaces.
- **Dark Text Secondary** (`#A7ACB1`): Secondary labels and metadata in dark mode.

## 3. Typography Rules

### Font Family
- **Latin UI / Display**: `Montserrat`, with fallbacks: `Segoe UI, Helvetica Neue, Arial, sans-serif`
- **Traditional Chinese UI / Body**: `Noto Sans TC`, with fallbacks: `PingFang TC, Microsoft JhengHei, sans-serif`
- **Monospace**: `SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace`
- **Numeric Behavior**: Use `font-variant-numeric: tabular-nums` for metrics, firmware versions, tables, and logs

### Hierarchy

| Role | Font | Size | Weight | Line Height | Letter Spacing | Notes |
|------|------|------|--------|-------------|----------------|-------|
| App Hero | Montserrat | 40px (2.5rem) | 700 | 1.15 | -0.02em | Main dashboard or device page title |
| Page Title | Montserrat / Noto Sans TC | 32px (2rem) | 700 | 1.20 | -0.01em | Primary page heading |
| Section Title | Montserrat / Noto Sans TC | 24px (1.5rem) | 600 | 1.25 | normal | Section headers with green keyline |
| Panel Title | Montserrat / Noto Sans TC | 18px (1.125rem) | 600 | 1.33 | normal | Cards, drawers, modal titles |
| Data Value | Montserrat | 20px (1.25rem) | 700 | 1.20 | normal | KPI metrics and counters |
| Body | Noto Sans TC / Montserrat | 16px (1rem) | 400 | 1.50 | normal | Standard reading text |
| Body Dense | Noto Sans TC / Montserrat | 14px (0.875rem) | 500 | 1.43 | normal | Tables, settings rows, compact lists |
| UI Label | Montserrat | 13px (0.8125rem) | 600 | 1.23 | 0.04em | Filters, nav labels, tiny English UI |
| Caption | Noto Sans TC / Montserrat | 12px (0.75rem) | 500 | 1.40 | normal | Metadata, timestamps, field help |
| Status Chip | Montserrat | 12px (0.75rem) | 600 | 1.33 | 0.06em | Short English status labels only |
| Mono Body | Monospace | 13px (0.8125rem) | 500 | 1.54 | normal | Logs, CLI, firmware strings |
| Mono Small | Monospace | 12px (0.75rem) | 500 | 1.40 | normal | Dense telemetry or inline diagnostics |

### Principles
- **Bilingual by default**: All major layouts must survive mixed English + Traditional Chinese labels without reflowing into awkward visual weight.
- **Uppercase selectively**: Uppercase is acceptable for short English labels and status chips, but never for Chinese copy and never for long navigation text.
- **Headline restraint**: Product / backoffice pages should live mostly in the 24-40px heading range. Avoid oversized marketing-style display typography.
- **Numbers must align**: Metrics, IP addresses, version numbers, uptime values, and throughput columns should always use tabular numerals.
- **Chinese needs breathing room**: For longer Chinese paragraphs, favor the `Body` and `Caption` line-heights rather than the tighter Latin display rhythm.

## 4. Component Stylings

### Buttons

**Primary (Apply / Save / Confirm)**
- Background: `#99CC00`
- Text: `#000000`
- Height: 40px
- Padding: 0 16px
- Radius: 6px
- Border: 1px solid `#99CC00`
- Hover: `#A8D426`
- Active: `#ADD633`
- Focus: green focus ring + visible outline offset

**Secondary (System / Utility)**
- Background: `#3C4043`
- Text: `#FFFFFF`
- Height: 40px
- Radius: 6px
- Hover: `#595D5F`
- Active: slightly darker graphite

**Tertiary / Ghost**
- Background: `#FFFFFF`
- Text: `#3C4043`
- Border: 1px solid `#DADCE0`
- Radius: 6px
- Hover: `#F1F3F4`
- Use: low-risk actions, toolbar controls, modal secondary action

**Destructive**
- Background: `#DC3545`
- Text: `#FFFFFF`
- Border: 1px solid `#DC3545`
- Hover: slightly darker red
- Use: reset, delete, disconnect, revoke

### Navigation
- Global top bar: `#3C4043` background, compact height (56-64px), white logo/wordmark
- Primary workspace navigation can use a dark left rail (`#3C3D41`) with muted text and a green active marker
- Active nav state is indicated by a 3-4px green bar, green keyline, or subtle green tint; avoid full bright-green pills
- Secondary tabs live on light surfaces with a green underline or bottom border
- Breadcrumbs and page paths use `#5F6368` text with subdued separators

### Cards & Containers
- Standard card background: `#FFFFFF`
- Standard border: 1px solid `#DADCE0`
- Radius: 6px
- Padding: 16-24px depending on density
- Default elevation: minimal; use border first, shadow second
- Distinctive Arcadyan treatment: add a green top rule or left keyline on primary panels and section headers
- Dark card variant: `#3C4043` background, `#5F6368` border, `#DADCE0` text

### KPI Tiles
- Two-line hierarchy: small label + large metric + optional delta/status row
- Value uses `Data Value` style with tabular numerals
- KPI tiles should remain quiet: white or graphite surface, green only for positive emphasis or active selection
- Avoid glossy gradients, oversized icons, or consumer-style promo blocks

### Tables & Data Grids
- Header background: `#F1F3F4`
- Header text: 13-14px semibold
- Default row height: 44px; compact mode: 36px
- Borders: horizontal dividers in `#DADCE0`
- Numeric columns: right-aligned with tabular numerals
- Row selection: green left border, subtle green tint, or 2px inset indicator
- Inline actions should appear on row hover/focus, not permanently overload every row

### Inputs & Filters
- Field background: `#FFFFFF`
- Border: 1px solid `#DADCE0`
- Radius: 6px
- Standard height: 40px; compact height: 32px
- Focus: border shifts to `#99CC00` with a soft green halo
- Filter bars may sit on `#F1F3F4` and use quiet bordered inputs
- Pills are reserved for segmented filters, tiny toggles, and chips only

### Status & Alerts
- Info: `#00ADDC` text/icon with low-opacity blue background
- Success: `#1AB39F` text/icon with low-opacity teal background
- Warning: `#FEB80A` text/icon with low-opacity amber background
- Error: `#DC3545` text/icon with low-opacity red background
- Health chips should remain compact and legible in both light and dark themes

### Logs, Code & Diagnostics
- Use dark surfaces for logs and terminal-like views even inside a light workspace
- Background: `#3C3D41` or darker neutral shell
- Text: `#DADCE0`
- Font: monospace 12-13px
- Semantic highlights: green for pass, cyan for info, amber for warning, red for failure
- Preserve strict alignment and visible timestamps

### Charts & Monitoring Panels
- Prefer clean lines, simple bars, and compact legends
- Use the PPT-derived accent set for multi-series charts, with green as the primary "healthy" series
- Avoid decorative gradients in product UI charts
- Grid lines and axes should remain low-contrast and subordinate to the data

### Modals & Drawers
- Radius: 8px maximum
- Background: white (light) or graphite (dark)
- Shadow: stronger than cards but still restrained
- Titles should align with a green keyline or subtle green accent
- Footer actions are right-aligned and ordered by risk: tertiary, secondary, primary/destructive

## 5. Layout Principles

### Spacing System
- Base unit: 4px
- Common scale: 4, 8, 12, 16, 24, 32, 40, 48, 64
- Dense modules can use 12px and 16px internally; section-to-section rhythm should start at 24px

### Grid & Container
- Breakpoints align to the current Arcadyan web system: 360px, 600px, 1024px, 1440px
- App shell pattern: top bar + optional left rail + content canvas
- Standard content max width: 1280-1300px on large screens
- Forms and settings stacks should prefer narrower readable columns (560-720px)
- Data views, tables, charts, and diagnostics can expand full-width inside the workspace

### Dashboard Composition
- Preferred order: page title, KPI strip, filters/toolbars, primary data panels, secondary supporting panels
- Major sections should be separated by whitespace and green rules, not by heavy decoration
- Persistent controls belong in toolbars or side panels, not inside every card

### Whitespace Philosophy
- Calm between modules, efficient inside modules
- Do not imitate marketing landing pages with giant empty hero blocks
- Use breathing room to separate tasks, not to create spectacle

### Border Radius Scale
- **0px**: full-width dividers, table edge treatments, hard separators
- **4px**: tiny controls, internal badges, inline utility buttons
- **6px**: default buttons, cards, inputs, dropdowns
- **8px**: modal, drawer, elevated overlay
- **9999px**: chips and segmented toggles only

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Level 0 | Flat canvas, white or graphite background | Main workspace or dark monitoring canvas |
| Level 1 | Border-only panel, no visible shadow | Standard cards, forms, filter areas |
| Level 2 | Soft shadow `0 2px 4px rgba(0, 0, 0, 0.075)` | Hovered panels, dropdowns, floating utility panels |
| Level 3 | Medium shadow `0 8px 16px rgba(0, 0, 0, 0.15)` | Drawers, sticky toolbars, advanced overlays |
| Level 4 | Deep shadow `0 16px 48px rgba(0, 0, 0, 0.175)` | Modal dialogs, critical overlays, full-screen debug tools |

**Depth Rules**
- Prefer borders and section keylines before shadows
- Green keylines communicate hierarchy more clearly than extra elevation
- In dark mode, rely even less on shadow; use contrast and border clarity instead

## 7. Do's and Don'ts

### Do
- Use Arcadyan Green as a precision accent, never as a wallpaper color
- Keep the app shell dark and the working surface light for standard product workflows
- Build for bilingual content from the first wireframe
- Use green keylines to signal hierarchy and active context
- Keep tables readable, aligned, and compact
- Use chart colors systematically: green first, cyan/periwinkle second, magenta only for contrast or anomaly
- Reserve dark panels for monitoring, logs, diagnostics, and focused system tasks

### Don't
- Don't turn the interface into a consumer marketing page
- Don't flood large surfaces with bright green
- Don't use oversized radii or playful rounded cards
- Don't rely on heavy animation, blur, or glassmorphism
- Don't use all-caps on Chinese copy
- Don't scatter status colors randomly; each semantic hue should have one consistent job
- Don't make every card look elevated; most modules should stay flat and disciplined

## 8. Responsive Behavior

### Breakpoints

| Name | Width | Key Changes |
|------|-------|-------------|
| Mobile | <600px | Single-column layout, stacked KPI cards, condensed toolbars |
| Tablet | 600-1023px | Two-column forms, collapsible rail, wrapped KPI strips |
| Desktop | 1024-1439px | Full app shell, left rail visible, standard panel grid |
| Large Desktop | >=1440px | Wider data canvas, 3-4 panel grids, larger diagnostics layouts |

### Touch Targets
- Minimum interactive target: 40x40px
- Dense desktop tables can go smaller visually, but touch affordances must expand on tablet/mobile

### Collapsing Strategy
- Left rail collapses to drawer below desktop
- Filter bars become stacked groups or slide-down panels on mobile
- Tables should preserve the most important columns first; secondary columns can collapse or scroll
- KPI strips should wrap before shrinking typography too aggressively
- Log panels remain full-width and can stack metadata above content on small screens

### Dark Variant Behavior
- Dark mode is not a theme inversion for every screen; use it intentionally for monitoring-heavy contexts
- If a screen switches to dark, preserve the same information hierarchy and green accent logic

## 9. Agent Prompt Guide

### Quick Color Reference
- Brand accent: `#99CC00`
- Workspace background: `#FFFFFF`
- Secondary surface: `#F1F3F4`
- Border: `#DADCE0`
- Body text: `#666666`
- Secondary text: `#5F6368`
- Dark chrome: `#3C4043`
- Dark canvas: `#3C3D41`
- Info: `#00ADDC`
- Success: `#1AB39F`
- Warning: `#FEB80A`
- Error: `#DC3545`

### Prompt Patterns
- "Build an Arcadyan broadband gateway admin dashboard with a light workspace, dark graphite navigation, and lime-green keylines for the active section."
- "Use Montserrat for English UI labels, Noto Sans TC for Traditional Chinese content, and tabular numerals for all metrics, firmware versions, and IP data."
- "Design the screen like an operator console: restrained cards, compact tables, quiet borders, and only purposeful color."
- "Use Arcadyan Green for Apply / Save / active navigation only. Keep large surfaces white, soft gray, or graphite."
- "For diagnostics and logs, switch to a dark monitoring panel while preserving the same green accent logic."

### Anti-Patterns for Agents
- Do not generate a consumer landing page, startup gradient hero, or playful SaaS illustration style
- Do not make bright green the main background color
- Do not use oversized soft shadows or oversized rounded corners
- Do not treat every module like a marketing card
- Do not break bilingual alignment with overly narrow columns or fragile label spacing
