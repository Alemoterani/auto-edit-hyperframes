"""Named ffmpeg looks for `--look`, stored as pipeline.json "video_filter".

The filter runs once, at full resolution, before graphics and captions are
composited (overlay stage, or caption stage when there are no overlays).
Each look upscales to 1080x1920 (vertical shorts) so text renders sharp.
"""
from __future__ import annotations

LOOKS: dict[str, str] = {
    # Even, well-lit footage: light denoise, skin smoothing, warm contrast, soft vignette.
    "studio": (
        "hqdn3d=3:3:8:8,scale=1080:1920:flags=lanczos,split[a][b];"
        "[b]bilateral=sigmaS=12:sigmaR=0.08[s];[a][s]blend=all_mode=normal:all_opacity=0.6,"
        "curves=master='0/0 0.12/0.05 0.5/0.57 0.85/0.93 1/1',eq=saturation=1.15,"
        "colorbalance=rm=0.05:gm=-0.03:bm=-0.05:rs=0.02:bs=-0.02,vignette=angle=PI/5,unsharp=5:5:0.4:5:5:0"
    ),
    # Dark room, single hard light: stronger denoise, lifts mid-tones on the face
    # while keeping the background dark, tames hot highlights, smooths skin.
    "low-light": (
        "hqdn3d=6:5:10:8,scale=1080:1920:flags=lanczos,split[a][b];"
        "[b]bilateral=sigmaS=14:sigmaR=0.09[s];[a][s]blend=all_mode=normal:all_opacity=0.55,"
        "curves=master='0/0 0.04/0.035 0.15/0.19 0.4/0.52 0.7/0.78 0.9/0.88 1/0.94',eq=saturation=1.06,"
        "colorbalance=rm=0.02:bm=-0.02:rh=-0.02:gh=-0.01,vignette=angle=PI/4.5,unsharp=5:5:0.55:5:5:0"
    ),
}
