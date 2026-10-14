# Prompting MiniMax-H3

H3 does not take a loose sentence and improvise. It takes a structured
description, and the difference in output quality is large. This app builds that
structure for you, but it helps to know what it is building and why.

The format is called **H3-Context-IR** -- Context Intermediate Representation.
It splits a request into labelled sections instead of one paragraph, so the
model knows which words are setting, which are camera, which are dialogue, and
which are sound.

The official guides are vendored in this directory:

- [`VIDEO_PROMPT_WRITING_GUIDE_base_en.md`](VIDEO_PROMPT_WRITING_GUIDE_base_en.md)
  -- text-to-video and image-to-video
- [`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`](VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)
  -- reference-to-video

Read them if you want the full rules. This page is the practical summary.

## Text to Video (`t2va`)

Three sections, in this order.

```text
integrated_multimodal_description: <style>. The scene is set in <setting>.
Lighting: <lighting>. [Shot 1] <shot size>. <camera move>. <what happens>.
overall_soundscape: <ambience and physical sounds>
non_diegetic_music: <music only the audience hears>
```

`integrated_multimodal_description` carries the visuals. It opens with style and
setting, then walks the shots in timeline order. `overall_soundscape` is what a
microphone in the scene would pick up -- wind, traffic, a humming server rack.
`non_diegetic_music` is score the characters cannot hear.

## Image to Video (`fl2va`)

Same three sections, plus a keyframe clause. One image pins the first frame; two
images pin the first and the last.

The composer writes this as prose in the shot, following the guide:

- one image: "the first frame fully references `<Picture 1>`"
- two images: "the first frame fully references `<Picture 1>`" and
  "the final frame fully references `<Picture 2>`"

In the request payload these become `conditions` entries with
`"role": "keyframe"` and `frame_index` `0` for the first frame and `-1` for the
last.

## Reference to Video (`ref2va`)

Six sections, in this order. This is the format with the most rules, because
the model has to track which reference does what.

```text
subject_definitions:    what each <Picture N>, <Video N>, <Audio N> denotes
summary:                [relationship tag] what the target video shows
retention_analysis:     <Label> (appears in [Shot N]): <policy> - <detail>
detailed_description:   [Shot N] ... prose that reuses the labels
overall_soundscape:     ambience and physical sounds
non_diegetic_music:     audience-only score, or N/A
```

### Reference labels

Give each input a label and keep its meaning stable across every section:

- `<Subject N>` -- a person, environment or object that gets its own definition
- `<Picture N>` -- an image
- `<Video N>` -- a source video
- `<Audio N>` -- an audio track

Once a label means something in `subject_definitions`, it means the same thing
everywhere else. If a `<Picture N>` only identifies where another item came
from, cite it inside that item's line instead of giving it its own.

### Retention policies

`retention_analysis` says what happens to each referenced item. Use the guide's
vocabulary exactly:

| Policy | Meaning |
| --- | --- |
| `fully_preserved` | kept as-is |
| `partially_preserved` | kept, but with changes |
| `fully_copy` | reused verbatim (audio) |
| `partially_copy` | reused in part (audio) |
| `reference` | informs the target without being copied |

An item that appears in specific shots says so: `<Picture 1> (appears in
[Shot 1]): fully_preserved - ...`.

### The summary tag

The summary opens with a bracketed tag naming the relationships in play, for
example `[reference generation + image reference + audio reference]` or
`[video editing + audio reference + audio reuse]`.

## Camera language

The guide is specific: write motion, then amplitude, then speed.

```text
The camera pushes in slow, steady.
The camera pans left, subtle, at a measured pace.
The camera holds a static shot.
```

Not "slow push in" and not "the camera moves slowly inward".

## Timecodes

Only shots after the first carry a timestamp, formatted `HH:MM:SS.mmm`:

```text
[Shot 1] A wide shot of the street.
[Shot 2] At 00:04.500, close-up of the sign.
```

## Dialogue

Wrap spoken lines in `<d>` tags with a language tag:

```text
The speaker delivers <d>[English] Follow the wind, live free.</d>.
```

Bare lines get wrapped for you, using the language selected in the UI. Speakers
get `(S1)`, `(S2)` identifiers assigned in order of their first vocal event, and
the same identifier is reused for that speaker throughout.

## On-screen text

Text visible in the frame is described as prose, not as a tag:

```text
On-screen text reads "OPEN 24 HOURS".
```

## Sound

`overall_soundscape` and `non_diegetic_music` are separate on purpose. Ambience
and sound effects belong in the first. Score the audience alone hears belongs in
the second. If a reference audio clip provides both, describe the relationship
in both sections.

When there is no audience-only score, write `N/A` rather than omitting the
section.

## Practical advice

- **Be specific about style and light.** "Cinematic, live-action, 35mm film"
  and "warm golden hour backlight" do more than "nice lighting".
- **Describe sound even when you do not care about it.** H3 generates audio by
  default, so an empty soundscape section gets filled with something you did not
  ask for.
- **Keep references few and purposeful.** Nine images is a lot of tracking for
  the model; three good ones usually beat nine loose ones.
- **Watch the composer output.** The preview updates as you type. If the prompt
  reads badly there, it will render badly.
- **Paste a finished prompt into Raw prompt override** when you have one from
  elsewhere; the composer steps aside entirely.
