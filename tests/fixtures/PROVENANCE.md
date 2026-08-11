# Test fixtures — provenance

This repository is single-licence Apache-2.0 (see `NOTICE`). Binary assets get
their provenance recorded here so that stays checkable.

## `frontal_face_portrait.jpg`

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
