# Customer demo clips

Three 15-second 9:16 clips for a posture-correction clinic, Korean narration and
captions, professional tone, background music. One per Phase 4 feature.

| clip | shows |
|---|---|
| `demo_transition.mp4` | a different transition at each of the four scene joins — crossfade, fade through black, slide left, zoom in |
| `demo_panning.mp4` | a different camera motion per scene — zoom in, pan left, pan up, auto |
| `demo_graphics.mp4` | text box, circle highlight, logo and a NEW sticker together |

All three are H.264 / AAC with the moov atom at the front, so they start playing
on a phone without downloading the whole file first.

Rebuild them with:

```bash
cd backend
.venv/bin/python make_demos.py            # all three
.venv/bin/python make_demos.py --only graphics --sheets
```

`make_demos.py` fails if any clip does not land on 15s, since scene length depends
on how long the narration turns out to be.

## Why the backgrounds are gradients

No Pexels API key is configured, so the stock-footage provider falls back to
generated gradient cards. Two consequences worth knowing:

- **`demo_panning.mp4` does not really demonstrate panning.** A smooth gradient has
  almost no detail for the camera to move across, so the motion is hard to see.
  The feature itself is measured frame by frame in
  `../verification/step4-2-motion/`.
- Backgrounds are tone-coloured (navy/teal here for a professional tone) rather
  than photographic.

Set `PEXELS_API_KEY` and re-run `make_demos.py` to get the same three clips over
real footage — no code change needed.
