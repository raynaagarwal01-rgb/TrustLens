# TrustLens interface: design notes

**Subject:** a forensic evidence workbench for students, proctors and anyone handed a suspicious image.
**Primary job:** open a piece of evidence, see whether and where it was manipulated, understand why, and export a report that holds up.

## Tokens

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#E7ECEF` | Workbench surface: cool lab grey, not cream |
| `--sheet` | `#F7F9FA` | Panels and forms laid on the bench |
| `--ink` | `#14202B` | Text and strong rules (blue-black, not a tinted #111) |
| `--graphite` | `#566370` | Secondary text |
| `--rule` | `#C3CDD5` | Hairlines |
| `--marker` | `#F2C230` | Evidence-marker yellow: selection, focus, the measurement scale. Never decoration |
| `--viewer` | `#2B3036` | Neutral surround for judging images without colour bias |
| `--manipulated` / `--caution` / `--clear` | `#B3312A` / `#9A6410` / `#1D6E52` | Only ever mean the verdict bands |

**Type:** Archivo (variable width 62–125, weight 100–900) for everything. Condensed widths (65–80) carry verdicts and headings, the way evidence labels and case files use condensed lettering; width 100 for reading text. JetBrains Mono only for hashes and offsets, where fixed width aids comparison. Scale: 12 / 13 / 15 / 18 / 24 / 32 / 44.

## Layout

```
┌ locker ─┬ case header ─────────────────────────────── [Compare] [Export report] ┐
│ open    │ ┌ viewer (dark surround, measurement scale) ┐ ┌ verdict ─────────────┐ │
│ cases   │ │  photo ◀ wipe ▶ layer   + evidence marks   │ │ verdict in condensed │ │
│ samples │ └────────────────────────────────────────────┘ │ score on a ruled scale│ │
│         │  layer picker · magnifier                      │ reasons, linked to    │ │
│ status  │ ┌ details: findings │ tests │ metadata │ ...  │ marks on the image   │ │
└─────────┴────────────────────────────────────────────────┴───────────────────────┘
```
Left-aligned throughout. Below 1100 px the verdict moves under the viewer; below 760 px the locker becomes a drawer.

## Principles

1. **The evidence is the hero.** The image gets the most space; everything else annotates it.
2. **One bold element:** the measurement scale framing the viewer, with the drag-to-compare wipe. Everything around it stays quiet.
3. **Colour is a claim.** Red, amber and green appear only for verdict bands; yellow only for selection, focus and the scale.
4. **Every claim cites its source:** a forensic test, the vision model, a signed manifest, or an official record.
5. **Honest wording:** never "authentic"; experimental tools are labelled as such.
6. **Motion only answers actions**, plus one scan line while an analysis runs (disabled under reduced motion).

## Video, audio, batches, verification, demo (v0.4)

- **Video** keeps the ruler frame and the wipe; a 12-frame timeline sits under the stage. Each frame carries a 3 px score bar
  (red/amber/green from the AI review, grey when unscored) and the key frame has a marker-yellow top edge, so the analysis
  layers' source frame is visible without a label. "Play video" swaps the stage for the original file.
- **Audio** puts the spectrogram where the photo would be (same palette as the error-level map: ink to marker) and wipes to
  the waveform; edit points are full-height marks with the usual numbered tents.
- **Never green when unchecked**: a result made without the AI review, and every traceless voice note, uses the amber
  inconclusive treatment everywhere (verdict band, locker dot, PDF), because "nothing found" would read as "cleared".
- **In short** (verdict panel): the three-line summary with an English / हिंदी segmented switch; Hindi uses Noto Sans
  Devanagari (loaded only for Devanagari code points via unicode-range).
- **Batch** is a plain risk-sorted table, not cards: the score column is right-aligned tabular numbers so it scans.
- **Demo bar** is the one piece of non-user-triggered motion: a marker-yellow progress line along its bottom edge.
