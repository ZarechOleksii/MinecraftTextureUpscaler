# Names and versions

Three things carry a version: **presets** (the settings for one kind of texture), **profiles** (which preset a texture
gets), and the **package** itself. Each has its own rule for when the number changes. The rules are checked by
`tests/test_presets_toml.py` where a machine can check them.

## Presets: `family-vMAJOR.MINOR`

Examples: `solid-v1.6`, `cutout-v2.1`, `base-v1.0`.

The **family** says what the preset is for, not how it works:

| family | what it is for |
|---|---|
| `solid` | opaque, tiling textures: most of `textures/block/` ("solid blocks") |
| `cutout` | anything with fully see-through pixels: items, leaves, plants, glass-like overlays |
| `base`, `items-diag` | building blocks that other presets extend; never picked directly |
| `lines` | the experimental line drawing for 1px diagonal lines |

A new family needs a reason: a kind of texture that none of the existing ones fits. Names are lowercase, words are
separated by `-`, and the version is always written with both numbers (`v1.0`, not `v1`). In TOML the name needs
quotes because of the dot: `[preset."solid-v1.6"]`.

Every preset has a **status**:

| status | meaning |
|---|---|
| `base` | a building block for other presets; not meant to be picked directly |
| `stable` | ready to use; the newest release of the `standard` profile ships exactly these |
| `experimental` | may change or go away; no profile uses it |
| `superseded` | replaced by a newer version; kept so that older packs can be rebuilt |

and a one-line **changelog**: what this version does differently from the one it extends.

### When does the number change?

1. **A published preset is never edited.** If a change alters even one pixel of its output, it is a new version.
   (`tests/golden/expected.json` pins every preset, so an accidental edit fails the tests.)
2. **MINOR** (`solid-v1.6` to `solid-v1.7`): a targeted fix or tweak. Most textures look the same afterwards. The new
   preset `extends` the previous one and sets only what changed.
3. **MAJOR** (`solid-v1.x` to `solid-v2.0`): a new capability, or a look that changes for many textures (a new stage
   switched on, a different way to split regions). It may extend the old version or start again from `base-v*`.
4. **No new version** for changes that leave the output alone: descriptions, comments, the changelog text, documentation,
   and refactors that pass the golden sweep untouched.
5. A new version gets `status = "stable"` once a profile release ships it; the version it replaces becomes
   `superseded` in the same change. Do not delete superseded presets: other presets extend them, and people rebuild old
   packs from them.

## Profiles: `name-rN`, and a moving alias

A profile is a numbered **release**: `standard-r1`. The bare name `standard` is an *alias* that always points at the
newest release. It is the only moving name in the project. Use `standard` to get the best current result; use
`standard-r1` in a script that must keep producing the same pack.

A profile gets a **new release** whenever one of its rules changes or points at a different preset version, even if no
preset changed. Never edit a published release; add `standard-r2`, move the alias, and mark the presets the old release
used (and the new one does not) `superseded`. Other profiles that exist for a reason (like `legacy-cutout-v1-r1`) are
named for that reason and are numbered the same way.

## Asking for a preset on the command line

`--blocks`, `--items`, `--use` and `--describe` accept a full name (`solid-v1.4`) or a bare family name. `solid` and
`cutout` mean "the preset the chosen profile uses for that kind of texture", so `--blocks solid` follows the profile
as it moves from release to release, while `--blocks solid-v1.6` is pinned.

## The package: `pyproject.toml`, SemVer

- **Patch** (`0.2.0` to `0.2.1`): bug fixes, tooling and docs. Output of every published preset is unchanged.
- **Minor** (`0.2.x` to `0.3.0`): a new `standard` release, a new preset or tool, a new option. Packs built with
  `standard` change; packs pinned to a release do not.
- **Major**: removing or renaming a preset, profile or command-line option that was already public, or changing the
  output of a published preset.

While the package is `0.x`, treat "minor" as the breaking bump too. The pack cache is keyed by a hash of the library's
source, not by this number, so the number is for people, not for the cache.

## Adding or changing a preset: checklist

1. Does the change alter output? Then it is a new version (a new `[preset."..."]`), not an edit.
2. Pick MINOR or MAJOR by rules 2 and 3 above; set `extends`, `status` and `changelog`; write the `description`.
3. If it should ship, add a profile release that uses it, move the alias, and mark the replaced presets `superseded`.
4. Re-record the golden file (`python -m tests.make_golden`), run `regen4x-docs`, commit `docs/presets`.
5. Bump the package version as above.
