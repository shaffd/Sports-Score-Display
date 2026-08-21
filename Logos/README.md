# Local team logos

Store transparent PNG files by league and three-letter team abbreviation:

```text
Logos/
  MLB/NYY.png
  NFL/DET.png
  NHL/NYR.png
```

The renderer trims transparent padding, scales each logo without smoothing, and
keeps a visible center gap between the away and home marks. For especially wide
pairs, it crops only their outer edges, never by more than one-third.
If a PNG is missing, the display uses the team's abbreviation so games remain
readable.
