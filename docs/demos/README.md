# Customer demo clips

Three 15-second 9:16 clips for a posture-correction clinic: Korean narration and
captions, professional tone, stock footage backgrounds, background music. One clip
per Phase 4 feature.

| clip | shows |
|---|---|
| `demo_transition.mp4` | a different transition at each of the four scene joins — crossfade, fade through black, slide left, zoom in |
| `demo_panning.mp4` | a different camera motion per scene — zoom in, pan left, pan up, auto |
| `demo_graphics.mp4` | text box, circle highlight, logo and a NEW sticker together |

All three are H.264 / AAC with the moov atom at the front, so they start playing on
a phone without downloading the whole file first.

Rebuild with:

```bash
cd backend            # needs PEXELS_API_KEY in backend/.env
.venv/bin/python make_demos.py --sheets
```

`make_demos.py` fails if any clip does not land on 15s, since scene length depends
on how long the narration turns out to be.

## Why the stock clips are pinned by id

Searching Pexels returns a different clip per scene index with no regard for what
is actually in it. On the approved search terms — physiotherapy, posture, spine,
wellness clinic, stretching, foot care — that produced bare-skin massage
close-ups and near-nude figures: unusable for a clinic promo, and in one case the
circle highlight landed on a semi-nude torso.

Clips are therefore pinned by Pexels id, chosen by eye from the candidates for
those same terms. `CLIP_SOURCE` in `make_demos.py` records which term each id came
from and why it was picked, and pinning also makes a re-render reproducible.

Footage is from [Pexels](https://www.pexels.com/license/), free to use.

## Camera motion on footage

Motion is capped to the lightest strength on video backgrounds — footage already
moves, so the camera does not need to. That cap is deliberate and it is enough
here: the start/end frames in `pan_startend.jpg` (regenerate with the snippet in
the PR) show zoom, pan left, pan up and auto all clearly displacing the frame,
because real footage has detail for the camera to travel across. Earlier gradient
backgrounds did not, which is why panning was invisible against them.
