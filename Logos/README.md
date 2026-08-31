# Local team logos

Store transparent PNG files by league and three-letter team abbreviation:

```text
Logos/
  MLB/NYY.png
  NFL/DET.png
  NHL/NYR.png
```

League title-card marks live separately from team marks:

```text
Logos/
  LEAGUES/MLB.png
  LEAGUES/NFL.png
  LEAGUES/NHL.png
```

League marks are centered horizontally and vertically on the full title card.
At the reference 64x32 resolution they fit within 60x28 pixels, preserving the
source aspect ratio and a minimum two-pixel vertical margin.

The renderer trims transparent padding, scales each logo without smoothing, and
keeps a visible center gap between the away and home marks. For especially wide
pairs, it crops only their outer edges, never by more than one-third.
If a PNG is missing, the display uses the team's abbreviation so games remain
readable.
