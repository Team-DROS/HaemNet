# HaemNet Design System

Light-first visual system and screen designs for the HaemNet hospital console and donor app.

## Contents

| Path | What it is |
|------|------------|
| `tokens.json` | Colour, typography, spacing, radius, shadow and status tokens. Source of truth for implementation. |
| `screens/Landing.dc.html` | Public landing page |
| `screens/Login.dc.html` | Hospital access / sign in |
| `screens/Dashboard.dc.html` | Command Center (hero screen) |
| `screens/Map.dc.html` | Dispatch map |
| `screens/Analytics.dc.html` | Network intelligence |
| `screens/DonorHome.dc.html` | Donor app home |
| `screens/DonorAlert.dc.html` | Donor urgent request |
| `screens/canvas.json` | Artboard layout index for the design canvas |

The `.dc.html` files are design-canvas sources, not runnable pages: they omit the canvas runtime
(`support.js`) and are meant to be read as layout and styling references while implementing the
React Native and React screens under `frontend/`.

## Direction

The interface is clinical, calm and operational. Emergency information carries the urgency; the
rest of the interface provides control. Depth comes from surface layering, spacing and typography,
not from shadows or gradients.

## Colour rules

Red (`#D92D20`) is reserved. It means critical, failed, or attention required, and nothing else.
The primary brand action colour is navy (`#0F1A2B`). Blue (`#2E5FEA`) marks work in progress,
violet (`#6941F5`) marks AI activity, green (`#0E9B6C`) marks confirmation, amber (`#E49412`)
marks a warning state such as ringing with no pickup.

Surfaces layer from the app canvas (`#F5F7FA`) up through white panels (`#FFFFFF`), secondary
bands (`#F8FAFC`) and selected rows (`#EDF2F9`). Borders stay at one pixel and shadows never
exceed `0 1px 3px` except for overlays and the request drawer.

## Typography

Space Grotesk carries headings, blood groups, ETAs and every important number. IBM Plex Sans
carries all normal interface text. IBM Plex Mono appears only on timestamps, donor IDs and
system IDs, never on body copy or labels.

## Emergency lifecycle

Every emergency moves through a single lifecycle, and it is rendered the same way everywhere:

```
triggered -> matched -> contacting -> answered -> accepted -> en route -> fulfilled
```

Completed stages use a filled green check, the current stage uses a pulsing blue node with an
animated progress rail, and future stages use hollow grey rings. Stage counts sit directly
beneath each stage label.

## Identity

The HaemNet mark is a droplet outline containing three connected nodes, with a single red node at
its centre: blood, network and connection. It is used once per screen at a small size and is never
enlarged as decoration.

## Implementation notes

The hospital console targets a 1600 x 1000 viewport with a 232px sidebar and a 60px top bar.
The donor app targets 390 x 844. Tables use 48px rows with hairline dividers rather than cards,
and status is shown as a coloured dot plus plain text; pills are reserved for accepted and
en route, where the state benefits from emphasis.
