# Hero sculpture — v5

Created on 27 September 2026 with the built-in `image_gen` tool. This is a generated raster artwork, not a photograph of a physical product.

## Files

- Website asset: `frontend/public/artwork/dialogue-sculpture-v5.webp` (900 × 900, RGBA, approximately 86 KiB).
- Original copied into the project: `frontend/public/artwork/dialogue-sculpture-v5.png` (1254 × 1254, RGBA, approximately 898 KiB).
- Generation source: `/Users/b_alkml/.codex/generated_images/01a0e249-eeb2-7650-93f8-e4f11b89a6ce/exec-152e9b2c-fdd5-4339-9507-c4e21304acc2.png`.
- Public URL path: `/artwork/dialogue-sculpture-v5.webp`.

## Prompt

Use case: stylized-concept. Asset type: premium 3D hero sculpture for a business negotiation training website. Create a photorealistic 3D studio sculpture of exactly TWO interlocking hollow speech-bubble frames, each a thick rounded extruded profile with one short speech tail. The upper-left frame is burnt vermilion / satin orange metal. The lower-right frame is polished dark graphite chrome. Their physically plausible interlocking arrangement is a visual metaphor of two sides coming to an agreement. Compact diagonal composition in a three-quarter perspective, tactile premium editorial product photography, soft studio lighting and beautifully controlled material reflections. Subject fully visible with 10 percent safe margin on all sides. Isolated on a genuinely transparent background with alpha, no floor or backdrop. No letters, no text, no people, no faces, no watermark. No neon glow, no blue or purple. Square composition.

## Method and verification

Generated with `transparent_background: true`; no input/reference images. Inspected the generated image and the optimized WebP. The composition contains two speech-bubble frames with orange and chrome finishes, no lettering, people, backdrop, or watermarks. The subject is fully visible; generated edge clearance is tighter than the requested 10% in places, so surrounding layout should supply the final breathing room.

Copied the original without changes, then used Pillow to resize proportionally to 900 × 900 with Lanczos and encode WebP at quality 88, method 6. No artistic modifications or background substitutions were made. Confirmed source alpha extrema 0–255; alpha was preserved in the WebP. The original generated source remains in place.
