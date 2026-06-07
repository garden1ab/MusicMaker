"""
prompt_composer.py
==================
The translation layer between the structured UI controls (genre, sub-genre,
instruments, energy, tempo, key, structure, genre-blend) and the *tag string*
that ACE-Step actually consumes.

ACE-Step is a tag/description driven model: the `prompt` field accepts
comma-separated tags ("synthwave, analog synths, driving bassline, 120 bpm,
A minor, energetic"). This module builds an optimally ordered, de-duplicated
tag string from the structured request, and also builds the `lyrics` scaffold
(structure tags such as [intro]/[verse]/[chorus]) that ACE-Step uses to shape
song structure.

Nothing here touches the GPU or torch, so it is fully unit-testable on its own.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Genre taxonomy:  genre -> (default tags, [sub-genres])
# ---------------------------------------------------------------------------
# The default tags seed the description with idiomatic production language for
# the genre; sub-genres refine it. This is intentionally broad rather than
# exhaustive - users can always fall back to the free-text prompt.
GENRES: dict[str, dict] = {
    "Electronic": {
        "tags": ["electronic", "synthesizers", "programmed drums"],
        "subgenres": {
            "House": ["house", "four on the floor", "deep bass", "soulful"],
            "Techno": ["techno", "hypnotic", "driving", "industrial"],
            "Trance": ["trance", "uplifting", "supersaw", "euphoric build"],
            "Drum and Bass": ["drum and bass", "breakbeat", "sub bass", "fast"],
            "Dubstep": ["dubstep", "wobble bass", "heavy drop", "syncopated"],
            "Synthwave": ["synthwave", "retro 80s", "analog synths", "neon"],
            "Ambient": ["ambient", "atmospheric pads", "evolving textures"],
            "IDM": ["idm", "glitch", "complex rhythms", "experimental"],
            "Lo-fi": ["lo-fi", "tape hiss", "mellow keys", "vinyl crackle"],
        },
    },
    "Hip Hop": {
        "tags": ["hip hop", "boom bap drums", "punchy"],
        "subgenres": {
            "Trap": ["trap", "808 bass", "hi-hat rolls", "dark"],
            "Boom Bap": ["boom bap", "sampled drums", "vinyl", "90s"],
            "Lo-fi Hip Hop": ["lo-fi hip hop", "jazzy chords", "relaxed", "study beats"],
            "Drill": ["drill", "sliding 808s", "menacing", "uk drill"],
            "Conscious": ["conscious rap", "soulful samples", "warm"],
        },
    },
    "Rock": {
        "tags": ["rock", "electric guitars", "live drums"],
        "subgenres": {
            "Classic Rock": ["classic rock", "70s", "guitar solo", "warm tube"],
            "Hard Rock": ["hard rock", "distorted guitars", "powerful"],
            "Indie Rock": ["indie rock", "jangly guitars", "lo-fi charm"],
            "Punk": ["punk", "fast", "raw", "aggressive"],
            "Metal": ["metal", "heavy distortion", "double kick", "intense"],
            "Post-Rock": ["post-rock", "cinematic build", "reverb-drenched"],
            "Grunge": ["grunge", "fuzzy guitars", "90s", "gritty"],
        },
    },
    "Pop": {
        "tags": ["pop", "catchy hooks", "polished production"],
        "subgenres": {
            "Synth Pop": ["synth pop", "bright synths", "danceable"],
            "Indie Pop": ["indie pop", "dreamy", "reverb vocals"],
            "Electropop": ["electropop", "glossy", "electronic beats"],
            "Dream Pop": ["dream pop", "shoegaze textures", "ethereal"],
            "Power Pop": ["power pop", "bright guitars", "upbeat"],
        },
    },
    "Jazz": {
        "tags": ["jazz", "swing feel", "upright bass", "brushed drums"],
        "subgenres": {
            "Bebop": ["bebop", "fast tempo", "complex harmony", "saxophone"],
            "Smooth Jazz": ["smooth jazz", "mellow", "electric piano", "sax"],
            "Jazz Fusion": ["jazz fusion", "electric", "virtuosic", "groovy"],
            "Bossa Nova": ["bossa nova", "nylon guitar", "soft", "brazilian"],
            "Big Band": ["big band", "brass section", "swing", "energetic"],
        },
    },
    "Classical": {
        "tags": ["classical", "orchestral", "acoustic"],
        "subgenres": {
            "Cinematic": ["cinematic", "epic orchestra", "sweeping strings"],
            "Piano Solo": ["solo piano", "expressive", "intimate"],
            "String Quartet": ["string quartet", "chamber", "elegant"],
            "Baroque": ["baroque", "harpsichord", "ornate", "counterpoint"],
            "Romantic": ["romantic era", "lush strings", "emotional"],
            "Minimalist": ["minimalist", "repetitive motifs", "hypnotic"],
        },
    },
    "R&B / Soul": {
        "tags": ["r&b", "soulful", "smooth vocals", "groovy bass"],
        "subgenres": {
            "Neo-Soul": ["neo-soul", "warm rhodes", "lush chords", "laid-back"],
            "Classic Soul": ["classic soul", "60s", "horns", "motown"],
            "Contemporary R&B": ["contemporary r&b", "lush", "modern production"],
            "Funk": ["funk", "slap bass", "tight groove", "wah guitar"],
        },
    },
    "Folk / Acoustic": {
        "tags": ["folk", "acoustic guitar", "organic", "intimate"],
        "subgenres": {
            "Singer-Songwriter": ["singer-songwriter", "fingerpicked guitar", "heartfelt"],
            "Americana": ["americana", "banjo", "rootsy", "warm"],
            "Celtic": ["celtic", "fiddle", "tin whistle", "traditional"],
            "Indie Folk": ["indie folk", "layered harmonies", "dreamy"],
        },
    },
    "Latin": {
        "tags": ["latin", "percussion", "rhythmic"],
        "subgenres": {
            "Reggaeton": ["reggaeton", "dembow rhythm", "club", "punchy"],
            "Salsa": ["salsa", "brass", "congas", "energetic"],
            "Bossa Nova": ["bossa nova", "nylon guitar", "smooth"],
            "Cumbia": ["cumbia", "accordion", "danceable"],
        },
    },
    "World": {
        "tags": ["world music", "traditional instruments"],
        "subgenres": {
            "Afrobeat": ["afrobeat", "polyrhythmic", "horns", "groovy"],
            "Reggae": ["reggae", "offbeat skank", "dub bass", "laid-back"],
            "Indian Classical": ["indian classical", "sitar", "tabla", "raga"],
            "Flamenco": ["flamenco", "spanish guitar", "passionate", "palmas"],
        },
    },
    "Cinematic / Score": {
        "tags": ["cinematic", "film score", "emotive"],
        "subgenres": {
            "Epic Trailer": ["epic", "trailer music", "huge drums", "choir"],
            "Ambient Score": ["ambient score", "drones", "tension"],
            "Action": ["action score", "driving percussion", "brass stabs"],
            "Emotional": ["emotional score", "solo piano", "strings", "tender"],
        },
    },
}


# ---------------------------------------------------------------------------
# Energy:  level (0-100 or named) -> descriptors
# ---------------------------------------------------------------------------
ENERGY_BANDS = [
    (0, 15, ["very calm", "ambient", "sparse", "soft dynamics"]),
    (15, 35, ["mellow", "relaxed", "gentle groove"]),
    (35, 55, ["moderate energy", "steady groove"]),
    (55, 75, ["energetic", "driving", "uplifting"]),
    (75, 90, ["high energy", "intense", "powerful"]),
    (90, 101, ["explosive", "maximum intensity", "frenetic", "huge dynamics"]),
]


# ---------------------------------------------------------------------------
# Tempo: named feel -> representative BPM (used when no explicit BPM given)
# ---------------------------------------------------------------------------
TEMPO_NAMES = {
    "very slow": 55,
    "slow": 72,
    "relaxed": 88,
    "moderate": 104,
    "upbeat": 120,
    "fast": 136,
    "very fast": 152,
    "frenetic": 174,
}


# ---------------------------------------------------------------------------
# Vocals
# ---------------------------------------------------------------------------
VOCAL_GENDERS = {
    "Female": ["female vocals"],
    "Male": ["male vocals"],
    "Androgynous": ["androgynous vocals"],
    "Choir": ["choir", "group vocals", "harmonized"],
    "Child": ["child vocals"],
}

# Singing techniques / timbres expressed as prompt tags.
VOCAL_STYLES = [
    "soulful", "powerful belting", "breathy", "raspy", "smooth", "airy",
    "falsetto", "operatic", "whisper", "gritty", "emotional", "warm",
    "autotuned", "rap", "spoken word", "vibrato", "harmonies", "ad-libs",
    "energetic delivery", "intimate", "anthemic",
]

# Top languages ACE-Step handles well.
LANGUAGES = [
    "English", "Chinese", "Spanish", "Japanese", "Korean", "French",
    "German", "Italian", "Portuguese", "Russian",
]


def _vocal_descriptors(gender, styles, language) -> list[str]:
    tags: list[str] = []
    if gender and gender in VOCAL_GENDERS:
        tags.extend(VOCAL_GENDERS[gender])
    elif gender:
        tags.append(f"{gender} vocals".lower())
    if styles:
        tags.extend(styles)
    if language and language.lower() != "english":
        tags.append(f"{language} lyrics")
    return tags


def _energy_descriptors(energy) -> list[str]:
    """Map an energy value (0-100 int, or a named band) to descriptors."""
    if energy is None:
        return []
    if isinstance(energy, str):
        name = energy.strip().lower()
        named = {
            "ambient": 8, "chill": 25, "mellow": 25, "moderate": 45,
            "energetic": 65, "intense": 82, "explosive": 95,
        }
        energy = named.get(name)
        if energy is None:
            return [name]  # pass the raw word through
    try:
        e = max(0, min(100, int(energy)))
    except (TypeError, ValueError):
        return []
    for lo, hi, words in ENERGY_BANDS:
        if lo <= e < hi:
            return list(words)
    return []


def _tempo_to_bpm(tempo) -> Optional[int]:
    """Accept either an explicit BPM number or a named tempo feel."""
    if tempo is None or tempo == "":
        return None
    if isinstance(tempo, (int, float)):
        return int(tempo)
    s = str(tempo).strip().lower()
    if s.replace(" ", "").replace("bpm", "").isdigit():
        return int(s.replace(" ", "").replace("bpm", ""))
    return TEMPO_NAMES.get(s)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def build_lyrics(
    user_lyrics: Optional[str],
    structure: Optional[list[str]],
    instrumental: bool,
) -> str:
    """
    Build the ACE-Step `lyrics` field.

    ACE-Step sings whatever is in this field, using bracketed structure tags
    such as [verse]/[chorus]/[bridge] to shape song form.

    Rules:
    * instrumental  -> "[instrumental]" (+ any chosen structure markers)
    * vocals + user lyrics:
        - if the lyrics already contain bracket tags, trust them verbatim;
        - otherwise return the lyrics as written (line breaks help vocal sync).
    * vocals + no lyrics + structure -> emit structure tags so the model
      improvises vocals that follow that form.
    * vocals + nothing -> empty (model decides).
    """
    structure_tags = []
    for section in (structure or []):
        tag = section.strip().lower().replace(" ", "")
        if not tag:
            continue
        if not tag.startswith("["):
            tag = f"[{tag}]"
        structure_tags.append(tag)

    if instrumental:
        if structure_tags:
            return "[instrumental]\n" + "\n".join(structure_tags)
        return "[instrumental]"

    if user_lyrics and user_lyrics.strip():
        return user_lyrics.strip()

    if structure_tags:
        return "\n".join(structure_tags)
    return ""


def compose(
    *,
    mode: str = "genre",                      # "genre" | "text"
    text_prompt: Optional[str] = None,        # used when mode == "text"
    genre: Optional[str] = None,
    subgenre: Optional[str] = None,
    blend_genre: Optional[str] = None,
    blend_amount: int = 0,                    # 0-100, how much of blend_genre to mix in
    instruments: Optional[list[str]] = None,
    energy=None,                              # 0-100 or named
    tempo=None,                               # bpm int or named feel
    key: Optional[str] = None,                # e.g. "A minor"
    structure: Optional[list[str]] = None,    # e.g. ["intro","verse","chorus",...]
    instrumental: bool = True,
    extra_tags: Optional[str] = None,
    # --- vocals ---
    lyrics: Optional[str] = None,             # raw lyrics text
    vocal_gender: Optional[str] = None,
    vocal_styles: Optional[list[str]] = None,
    language: Optional[str] = None,
    # --- reference clip role ---
    ref_role: str = "music",                  # "music" | "voice"
) -> dict:
    """
    Returns a dict:  { "prompt": <tag string>, "lyrics": <lyrics/scaffold> }
    suitable for handing straight to the ACE-Step pipeline.
    """
    tags: list[str] = []

    if mode == "text" and text_prompt:
        # Free-text mode: the user's description leads, structured knobs refine.
        tags.append(text_prompt.strip())
    else:
        # Genre mode: assemble from the taxonomy.
        if genre and genre in GENRES:
            tags.extend(GENRES[genre]["tags"])
            if subgenre and subgenre in GENRES[genre]["subgenres"]:
                tags.extend(GENRES[genre]["subgenres"][subgenre])
        elif genre:
            tags.append(genre)
            if subgenre:
                tags.append(subgenre)

        # Genre blend
        if blend_genre and blend_amount and blend_amount > 0:
            blend_seed = GENRES.get(blend_genre, {}).get("tags", [blend_genre])
            if blend_amount >= 60:
                tags.append(f"heavy {blend_genre} influence")
            elif blend_amount >= 30:
                tags.append(f"{blend_genre} fusion")
            else:
                tags.append(f"subtle {blend_genre} elements")
            tags.extend(blend_seed[:2])

    # Instruments (apply in both modes)
    if instruments:
        tags.extend(instruments)

    # Vocals vs instrumental
    if instrumental:
        tags.append("instrumental")
    else:
        tags.append("vocals")
        tags.extend(_vocal_descriptors(vocal_gender, vocal_styles, language))
        # When cloning/matching a reference voice, nudge timbre consistency.
        if ref_role == "voice":
            tags.append("consistent vocal timbre")

    # Energy
    tags.extend(_energy_descriptors(energy))

    # Tempo -> explicit BPM tag (ACE-Step responds well to "120 bpm")
    bpm = _tempo_to_bpm(tempo)
    if bpm:
        tags.append(f"{bpm} bpm")

    # Key
    if key:
        tags.append(key.strip())

    # Free-form extra tags
    if extra_tags:
        tags.extend([t.strip() for t in extra_tags.split(",") if t.strip()])

    tags = _dedupe_preserve_order(tags)
    prompt = ", ".join(tags)
    lyrics_field = build_lyrics(lyrics, structure, instrumental)

    return {"prompt": prompt, "lyrics": lyrics_field}


# Convenience for the API layer / frontend
def catalog() -> dict:
    """Serializable catalog of genres + subgenres for the UI dropdowns."""
    return {
        g: list(meta["subgenres"].keys()) for g, meta in GENRES.items()
    }


def vocal_catalog() -> dict:
    """Vocal-specific options for the UI."""
    return {
        "genders": list(VOCAL_GENDERS.keys()),
        "styles": list(VOCAL_STYLES),
        "languages": list(LANGUAGES),
    }


if __name__ == "__main__":
    # Tiny self-test
    import json
    out = compose(
        mode="genre",
        genre="Electronic",
        subgenre="Synthwave",
        blend_genre="Jazz",
        blend_amount=35,
        instruments=["analog synth", "drum machine", "saxophone"],
        energy=70,
        tempo=118,
        key="A minor",
        structure=["intro", "verse", "chorus", "verse", "chorus", "outro"],
        instrumental=True,
    )
    print(json.dumps(out, indent=2))
    print(json.dumps(catalog(), indent=2)[:400])
