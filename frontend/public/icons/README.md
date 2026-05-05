# Icons

These SVG placeholders work in modern browsers (Chrome, Firefox, Safari, Edge)
for favicons, PWA manifest icons, and modern iOS Add-to-Home-Screen.

## When to add PNG versions

Older iOS (< 16) and some Android launchers prefer PNG. For full coverage,
generate PNGs from these SVGs and add to `public/icons/`:

```
icon-192.png        — 192x192 (PWA)
icon-512.png        — 512x512 (PWA)
apple-touch-icon.png — 180x180 (iOS home screen)
```

## Quick generation

Using ImageMagick:
```bash
magick public/icons/icon.svg            -resize 192x192 public/icons/icon-192.png
magick public/icons/icon.svg            -resize 512x512 public/icons/icon-512.png
magick public/icons/apple-touch-icon.svg -resize 180x180 public/icons/apple-touch-icon.png
```

Or sharp (Node):
```bash
npx sharp-cli -i public/icons/icon.svg -o public/icons/icon-192.png resize 192 192
npx sharp-cli -i public/icons/icon.svg -o public/icons/icon-512.png resize 512 512
```

After adding PNGs, update `manifest.webmanifest` to reference them and
`layout.tsx` `metadata.icons.apple` to point at the PNG.

## Design

Replace these placeholder Cs with your actual logo when ready.
