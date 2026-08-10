# Onside Football Academy — Framer Design System Dossier

Extracted live from Framer project `GIUy1fDHOhRC9WKxUQmF` ("Onside Football Academy (copy)")
via `@framer/agent` session. All values are authoritative, not inferred.

---

## 1. Breakpoints

| Name | Media query | Canvas width |
|---|---|---|
| Desktop | `(min-width: 1200px)` | 1200px |
| Tablet | `(min-width: 810px) and (max-width: 1199.98px)` | 810px |
| Phone | `(max-width: 809.98px)` | 390px |

Sections are `width: 1fr` with `maxWidth: 1440px`. Inner content columns cap at
`maxWidth: 800px` (text/grids) or `1080–1200px` (wide media rows).

---

## 2. Color styles (14)

| Name | RGB | Hex | Framer token id (prefix) |
|---|---|---|---|
| Black | `rgb(0,0,0)` | `#000000` | `b2cfd56c` |
| White | `rgb(255,255,255)` | `#FFFFFF` | `4798a21f` |
| Dark Grey | `rgb(61,61,61)` | `#3D3D3D` | `51b2a4c4` |
| Medium Grey | `rgb(105,105,105)` | `#696969` | `dea74db5` |
| Light Grey | `rgb(242,242,242)` | `#F2F2F2` | `a8fad490` |
| **Accent** | `rgb(55,90,254)` | **`#375AFE`** | `ae45deec` |
| Sky Blue | `rgb(145,185,254)` | `#91B9FE` | `f0cffa2f` |
| Band | `rgb(28,38,137)` | `#1C2689` | `00cbbc63` |
| Green | `rgb(2,85,74)` | `#02554A` | `c7e7bb82` |
| Teal | `rgb(4,207,91)` | `#04CF5B` | `1e55d3cb` |
| Coral | `rgb(220,1,3)` | `#DC0103` | `08a3cf68` |
| Maroon | `rgb(128,20,15)` | `#80140F` | `90cf427c` |
| Orange | `rgb(242,110,34)` | `#F26E22` | `799ede3b` |
| Lemon | `rgb(188,238,6)` | `#BCEE06` | `e1b40eaa` |

**No dark-mode variant is defined on any style** (`dark: null` on all 14).
The site is light-only; "dark" sections are literal Black fills on a White page.

### Observed usage
- Page background: **White**
- Alternating dark sections (`Our Numbers`, `Programs`, `Testimonials`, `Events`,
  footer, testimonial card): **Black**, `radius: 24px`
- Light sections (`About Us`, `Benifits`, `Pricing`, `Facilities`): page White
- Decorative oval blobs on testimonial card: **Accent** + **Sky Blue**
- Stat tiles: **Maroon** and **Coral**

> **Alignment note:** Framer `Accent #375AFE` is near-identical to the Yielda
> frontend's current royal blue `#305AF6` (`oklch(0.542 0.237 266.3)`).
> The accent hue transfers essentially unchanged.

---

## 3. Type scale (9 styles)

| Style | Tag | Family | Weight | Phone (base) | Tablet ≥810 | Desktop ≥1200 | Letter-spacing | Line-height | Transform |
|---|---|---|---|---|---|---|---|---|---|
| Display | h1 | Boldonse | 400 | 52px | 38px | 44px | -0.04em | 150% | none |
| Heading 2 | h2 | Boldonse | 400 | 38px | 30px | 36px | -0.02em | 150% | none |
| Heading 3 | h3 | Boldonse | 400 | 34px | 26px | 34px | -0.02em | 150% | capitalize |
| Heading 4 | h4 | Manrope | 700 | 34px | 22px | 26px | -0.02em | 120% | capitalize |
| Heading 5 | h5 | Manrope | 700 | 30px | 22px | 24px | -0.02em | 150% | capitalize |
| Body | p | Manrope | 400 | 16px | — | — | -0.02em | 120% | none |
| Body L | p | Manrope | 400 | 20px | 18px | 18px | -0.04px | 140% | none |
| Body M | p | Manrope | 400 | 18px | 16px | 18px | -0.02em | 1.4em | none |
| Label | p | Manrope | 500 | 14px | — | — | 0.01em | 1.2em | none |

Note the scale is **not monotonic** — phone base is *larger* than tablet for the
headings (52 → 38 → 44). Framer's `minWidth: 0` value is the phone value.

### ⚠ Korean coverage — blocking constraint
Verified against the Google Fonts CSS API:
- **Boldonse**: `latin`, `latin-ext` only → **no Hangul**
- **Manrope**: `latin`, `latin-ext`, `cyrillic`, `cyrillic-ext`, `greek`, `vietnamese` → **no Hangul**

Yielda's product language is Korean. **Decision taken: use Paperlogy throughout**
(already self-hosted at `frontend/public/Paperlogy-1.001/`, 9 weights 100–900).
Boldonse and Manrope are dropped; Paperlogy carries the scale above.

Mapping: Boldonse 400 (display) → Paperlogy 800/900; Manrope 700 → Paperlogy 700;
Manrope 400 → Paperlogy 400; Manrope 500 (Label) → Paperlogy 500.
Paperlogy is geometric and heavy at 800/900, which is the closest available
substitute for Boldonse's display weight. Letter-spacing at -0.04em/-0.02em should
be re-tested on Hangul — tight tracking reads worse on syllabic blocks than Latin.

---

## 4. Spacing & layout rhythm

| Property | Desktop | Tablet | Phone |
|---|---|---|---|
| Section padding | `140px 40px` | `112px 40px` | `88px 10px` |
| Section gap | `64px` | `64px` | `32px` |
| Page container padding | `10px` | `10px` | `10px` |
| Footer padding | `64px 56px 40px 56px` | same | `40px 24px 32px 24px` |
| Footer inner gap | `64px` → `48px` → `28px` | | `36px` → `28px` |

Other recurring values:
- Card radius **24px**; hero/header radius **16px**
- Card padding **24px**; card inner gap **16–20px**
- Card row gap **16px**; two-column split gap **100px**; text block gap **20px**
- Grid gap `32px 24px`; link-list gap `14px`
- Hero: `height: 100vh`, `padding-top: 96px`, bottom-anchored content,
  `linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.7) 100%)` overlay

---

## 5. Page structure — Home (`/`)

Desktop total height ≈ 11,228px. Order:

| # | Section | Height | Fill | Notes |
|---|---|---|---|---|
| — | Smooth Scroll | 0 | — | external component, `intensity: 10` |
| 1 | Header / Hero | 800 | image + gradient | 100vh, headline + CTA row left, stat block right (35%) |
| 2 | About Us | 933 | White | 2-col split, then testimonial cards + stat tiles row |
| 3 | Our Numbers | 786 | **Black** | Section Label + title + 2×2 stat grid + description |
| 4 | Benifits | 801 | White | header + 3 × `Benifits Card` |
| 5 | Programs | 2912 | **Black** | **sticky** header + **sticky** stacked `Program Card`s (CMS-driven, 6 items) |
| 6 | Pricing | 837 | White | header + 2 × `Pricing Card` |
| 7 | Testimonials | 778 | **Black** | image (max 400px) + `Testimonial Reel` |
| 8 | Facilities | 1008 | White | header + `CinematicSlideshow` (code component, aspect 1.64) |
| 9 | Events | 838 | **Black** | header + `Section` component (max 1080px) |

Layout template `Template` (applied to all pages) adds: fixed `Navbar`
(98.33% width, max 1440px), an `FAQs` section, and the Black footer
(CTA + Links / Social Media / newsletter form + wordmark).

Other pages: `/contact-us`, `/404`.

---

## 6. Components

**Custom (17):** Button · Modern Button · Main Button · Form button · Section Label ·
Section · Row · Navbar · Nav item · Icon tag · Benifits Card · Program Card ·
Pricing Card · Testimonial Reel · Testimonial Card · FAQs · Accordion

**Code (1):** `Slideshow.tsx` → `CinematicSlideshow` (~15KB)

**External (4):** Animated Number Counter · Phosphor · Layout Jump Preventer · Smooth Scroll

**Icon sets in use:** Mage, Basicons, Phosphor, Iconic, Lucide

---

## 7. CMS

**Training Programs** — 6 items (Under 6, Under 8, Under 10, Under 12, Under 15,
Elite Program). Fields: Title, Age, Frequency, Skill Level, Duration,
Icon *(type `unsupported`)*, Image. Drives the sticky Program Card stack.

---

## 8. Motion

- Framer transition default: `spring-physics 500 60 1 0s`
- Smooth-scroll wrapper at page root (intensity 10)
- Animated number counters in stat tiles
- Sticky-stacked program cards (scroll-driven)
- Cinematic slideshow in Facilities
