# Test fixtures — provenance

This repository is single-licence Apache-2.0 (see `NOTICE`). Binary assets get
their provenance recorded here so that stays checkable.

## `frontal_face_portrait.jpg` — the positive case

| | |
|---|---|
| **Source** | [Wikimedia Commons — `File:Official Portrait - Astronaut Michael A. Baker.jpg`](https://commons.wikimedia.org/wiki/File:Official_Portrait_-_Astronaut_Michael_A._Baker.jpg) |
| **Original** | [NASA Image and Video Library, `s85-41895`](https://images.nasa.gov/details-s85-41895) |
| **Author** | NASA |
| **Licence** | **Public domain** — a work of the U.S. federal government (`PD-USGov-NASA`) |
| **Modification** | Downscaled to 960 px wide by Wikimedia's thumbnailer. Original is 2400 × 3000. No other change. |
| **SHA-256** | `38214609dbc039a5f94b8824d176e0f2b3e828971e4bbbc7c79348b41dc29710` |

### Why this image

The perception tests and the replay harness need a photograph that MediaPipe
genuinely detects a face in. Synthetic colour blocks are not detected at all,
and bypassing the detector would assume away the very thing being measured
(`PLAN.md` §6) — MediaPipe's per-frame cost is what causes the backlog the
harness exists to quantify.

Requirements this image satisfies:

- **Frontal and unobstructed.** The face-width distance estimate reads the
  face-oval landmarks at both cheeks; a turned head or an occluding hand makes
  that width unstable.
- **Whole head with margin.** The harness scales the picture so the face spans
  a chosen pixel width, then composites it onto a canvas. A tight facial crop
  would put a hard rectangular edge exactly at the cheek landmarks. A
  head-and-shoulders portrait scaled down instead looks like a person standing
  further away — which is what is being simulated.
- **Plain, evenly lit, uncluttered.** Keeps detection deterministic across runs.
- **Freely reusable, with the copyright status stated by the publisher.**

An earlier candidate — a CC0 Unsplash macro portrait — was rejected on the
second point: the face filled the frame and both cheeks were cropped at the
edges.

### Note on the licence, and on its limits

The originating ticket asked for a CC0 image. This is not CC0, and the two are
not equivalent:

- **CC0** is a worldwide, jurisdiction-independent waiver made deliberately by
  the rights holder.
- **`PD-USGov`** is a statement that the work had no copyright *in the United
  States* to begin with, because a U.S. federal employee produced it in the
  course of their duties. Other jurisdictions are not bound to reach the same
  conclusion, though in practice NASA imagery is treated as freely reusable
  everywhere.

The substitution was accepted because the freedoms this project needs — redis-
tribute the file inside an Apache-2.0 repository, with no attribution
condition — hold under both. It should not be described as "the same as CC0".

Separately: **the subject is a living, identifiable person.** A free copyright
licence says nothing about personality or publicity rights, and NASA's own
guidance asks that its imagery not be used to imply endorsement. Using the
photograph as a face-detection fixture does not imply anything about the person
and is well within that; using it as, say, illustrative marketing for this
project would not be. Attribution is recorded above as courtesy, not
obligation.


## `turned_head_portrait.jpg` — the negative control

| | |
|---|---|
| **Source** | [Wikimedia Commons — `File:Jessica Meir official portrait in an EMU (B&W) (cropped).jpg`](https://commons.wikimedia.org/wiki/File:Jessica_Meir_official_portrait_in_an_EMU_(B%26W)_(cropped).jpg) |
| **Original** | NASA, via [flickr.com/photos/nasa2explore](https://www.flickr.com/photos/nasa2explore/33791970868/), photographed 2018-09-11 |
| **Author** | NASA |
| **Licence** | **Public domain** — a work of the U.S. federal government |
| **Dimensions** | 960 × 815, greyscale (the frontal fixture is 960 × 1200, colour) |
| **Modification** | Downscaled to 960 px wide by Wikimedia's thumbnailer. The Commons file is itself a crop of the NASA original; the *head* is not cropped and carries margin on every side — landmarks span x[320,506] y[159,375] in a 960 × 815 frame. No other change. |
| **SHA-256** | `3a5ef584b6bb85c622c34be9cadff51d7376da7fc5cb1901ed23aab173b4ffea` |

### Why this image

`is_looking` compares how far the nose sits from the midpoint of the cheeks
against `GAZE_OFFSET_RATIO`. With only a frontal photograph in the repository,
every gaze assertion in the suite could be satisfied by an implementation that
returned `True` and did nothing else. This is the photograph that fails it.

It was chosen **empirically, not by eye**. Fourteen public-domain portraits
were screened by running the project's own detector over each and reading the
offset ratio out; the head has to be turned far enough for MediaPipe to place
the nose past the threshold, and not so far that it stops finding a face at
all. Judging that from a thumbnail is guesswork — the criterion is a MediaPipe
output, so MediaPipe decided.

The pair straddles the threshold, but **not symmetrically**:

| | offset ratio | distance from threshold | verdict |
|---|---|---|---|
| `frontal_face_portrait.jpg` | 0.054 | 0.196 below | looking |
| **threshold** | **0.25** | | |
| `turned_head_portrait.jpg` | 0.330 | **0.080 above** | not looking |

The negative side has 2.4× less room than the positive one, and ticket 02's
notes record that MediaPipe's behaviour near this boundary is discontinuous —
so the thinner margin is on the more brittle side. The pair discriminates; it
is not two equally solid ends.

### The screening, in full

Fourteen public-domain portraits, each run through the project's own detector.
This was the only one both detected and judged not looking:

| offset | verdict | file |
|---|---|---|
| — | not detected | 2025 NASA Photographer Of The Year Winners |
| 0.011 | looking | Alexander Gerst, official portrait |
| 0.149 | looking | Alexander Gerst, official portrait in 2017 |
| — | not detected | Alexander Gerst, official portrait standing |
| 0.075 | looking | Andrew R. Morgan official portrait (1) |
| 0.082 | looking | Andrew R. Morgan official portrait (2) |
| — | not detected | Andrew R. Morgan official portrait (3) |
| 0.166 | looking | Jessica Meir official portrait in an EMU |
| — | not detected | Jessica Meir official portrait in an EMU (B&W) |
| 0.186 | looking | Jessica Meir … (B&W) (close) |
| **0.330** | **not looking** | **Jessica Meir … (B&W) (cropped)** ← chosen |
| 0.053 | looking | Mark Vande Hei, official portrait |
| 0.060 | looking | Mark Vande Hei, official portrait (cropped) |
| 0.000 | looking | Michael S. Hopkins, official portrait |

Four were not detected at all. A full profile is no use here: a test that
passes because nothing was found is asserting a detection failure and calling
it a gaze judgement.

The table is recorded because the alternative was a claim about work that left
no trace — "fourteen were screened" is not checkable, and the numbers are the
only part of that sentence anyone can act on.

### Where it falls short of the brief

The originating ticket asked for 「素背景、光線平均」 — a plain, evenly lit
background — as the frontal fixture's entry above certifies for itself. **This
one does not fully meet that.** The right half of the frame is an EVA suit:
hardware, a flag patch, hard specular highlights.

It was accepted anyway because the half containing the face *is* plain white
and evenly lit, and because the offset ratio depends only on landmark geometry,
so the clutter cannot move the number the pair exists to demonstrate. That is a
reason, not a exemption, and it is recorded here rather than left for someone
to notice.

### What is deliberately not tested

Where exactly the boundary sits. That is a property of MediaPipe's landmark
regression and of a threshold this project chose, not of anything the project
computes, and an assertion on it would break on a MediaPipe upgrade that
changed neither. The two fixtures assert their own verdicts and nothing about
the gap between them.
