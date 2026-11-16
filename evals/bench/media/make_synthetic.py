"""Make the SYNTHETIC voice notes and photos for the media bench, and their
manifests. Runs on a Mac (needs `say` and ffmpeg), not in the container:

    uv run --with pillow --with matplotlib --with numpy python evals/bench/media/make_synthetic.py

Writes evals/bench/media/synthetic/{voice.jsonl,photo.jsonl,voice/*.ogg,photo/*.jpg}.

Synthetic means best case: the voices are text-to-speech (one South African
English voice, no isiZulu/Sesotho/Afrikaans voice, so code-switched words are
read with English sounds) and the "handwriting" is a font on drawn paper.
The REAL set (media/real/, same manifest fields) is what counts.
"""

import json
import random
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "synthetic"

# ── Voice ────────────────────────────────────────────────────────────────────
# said:  the exact words spoken.   typed: how a learner would type the same.
# role "answer": a reply to `problem` (already open); `verdict` is what the
# code answer check gives the TYPED form.
Q, A = "question", "answer"
P_EQ, P_NEG, P_FR = "How do I solve 3x + 4 = 19?", "What is -8 + 3?", "How do I add 2/3 and 1/4?"
VOICE = [
    # exponents
    ("v01", 8, "exponents", "en", Q, "What is three squared plus four squared?", "What is 3^2 + 4^2?"),
    ("v02", 8, "exponents", "en", Q, "How do I simplify x to the power of five times x to the power of three?",
     "How do I simplify x^5 × x^3?"),
    ("v03", 12, "exponents", "en", Q, "Solve for x. Two to the power of x plus three equals thirty two.",
     "Solve for x: 2^(x+3) = 32"),
    ("v04", 8, "exponents", "en", Q, "What is two to the power of negative three?", "What is 2^-3?"),
    # fractions
    ("v05", 8, "fractions", "en", Q, "How do I add two thirds and one quarter?", P_FR),
    ("v06", 8, "fractions", "en", Q, "What is three over four divided by one half?", "What is 3/4 ÷ 1/2?"),
    ("v07", 8, "fractions", "en", Q, "Simplify twelve over eighteen.", "Simplify 12/18"),
    # negative numbers
    ("v08", 8, "negatives", "en", Q, "What is negative eight plus three?", P_NEG),
    ("v09", 8, "negatives", "en", Q, "Calculate minus six times minus seven.", "Calculate -6 × -7"),
    ("v10", 8, "negatives", "en", Q, "What is five minus negative two?", "What is 5 - (-2)?"),
    # brackets
    ("v11", 8, "brackets", "en", Q, "Expand three, open bracket, x plus four, close bracket.", "Expand 3(x + 4)"),
    ("v12", 8, "brackets", "en", Q, "Solve two bracket x minus one bracket equals ten.", "Solve 2(x - 1) = 10"),
    ("v13", 8, "brackets", "en", Q, "Simplify three a plus two b plus five a.", "Simplify 3a + 2b + 5a"),
    # equations
    ("v14", 8, "equations", "en", Q, "How do I solve three x plus four equals nineteen?", P_EQ),
    ("v15", 8, "equations", "en", Q, "Solve two x minus seven equals nine.", "Solve 2x - 7 = 9"),
    ("v16", 12, "equations", "en", Q, "Solve x squared minus five x plus six equals zero.", "Solve x^2 - 5x + 6 = 0"),
    ("v17", 12, "equations", "en", Q, "Find the derivative of f of x equals x cubed minus six x.",
     "Find the derivative of f(x) = x^3 - 6x"),
    ("v18", 8, "equations", "en", Q, "Solve x over three plus two equals five.", "Solve x/3 + 2 = 5"),
    # units and word problems
    ("v19", 8, "units", "en", Q,
     "What is the area of a rectangle that is eight centimetres by three point five centimetres?",
     "What is the area of a rectangle 8 cm by 3.5 cm?"),
    ("v20", 8, "units", "en", Q,
     "A taxi travels one hundred and twenty kilometres in one and a half hours. "
     "What is its average speed in kilometres per hour?",
     "A taxi travels 120 km in 1.5 hours. What is its average speed in km/h?"),
    ("v21", 8, "units", "en", Q, "Find the perimeter of a square with sides of seven point two metres.",
     "Find the perimeter of a square with sides of 7.2 m"),
    ("v22", 8, "units", "en", Q, "What is fifteen percent of two hundred and forty rand?", "What is 15% of R240?"),
    # short spoken answers
    ("v23", 8, "answers", "en", A, "x equals five", "x = 5", P_EQ, "correct"),
    ("v24", 8, "answers", "en", A, "x equals negative five", "x = -5", "Solve 2x + 16 = 6", "correct"),
    ("v25", 8, "answers", "en", A, "three x equals fifteen", "3x = 15", P_EQ, "step_forward"),
    ("v26", 8, "answers", "en", A, "x equals seven", "x = 7", P_EQ, "wrong"),
    ("v27", 8, "answers", "en", A, "negative five", "-5", P_NEG, "correct"),
    ("v28", 8, "answers", "en", A, "minus eleven", "-11", P_NEG, "wrong"),
    ("v29", 8, "answers", "en", A, "eleven over twelve", "11/12", P_FR, "correct"),
    ("v30", 8, "answers", "en", A, "twenty eight square centimetres", "28 cm^2",
     "What is the area of a rectangle 8 cm by 3.5 cm?", "correct"),
    ("v31", 12, "answers", "en", A, "x equals two or x equals three", "x = 2 or x = 3",
     "Solve x^2 - 5x + 6 = 0", "correct"),
    ("v32", 12, "answers", "en", A, "three x squared minus six", "3x^2 - 6",
     "Find the derivative of f(x) = x^3 - 6x", "correct"),
    # code-switched: a greeting or a sentence in another language, maths in English
    ("v33", 8, "code-switch", "zu", Q,
     "Sawubona Katlego, ngicela ungisize. How do I solve three x plus four equals nineteen?",
     "Sawubona Katlego, ngicela ungisize. " + P_EQ),
    ("v34", 8, "code-switch", "zu", Q, "Angiqondi ukuthi ngenzani la. What is negative eight plus three?",
     "Angiqondi ukuthi ngenzani la. " + P_NEG),
    ("v35", 8, "code-switch", "st", Q, "Dumela Katlego, ke kopa thuso. How do I add two thirds and one quarter?",
     "Dumela Katlego, ke kopa thuso. " + P_FR),
    ("v36", 8, "code-switch", "st", Q, "Ha ke utlwisise. Solve two x minus seven equals nine.",
     "Ha ke utlwisise. Solve 2x - 7 = 9"),
    ("v37", 8, "code-switch", "af", Q,
     "Hallo Katlego, ek verstaan nie hierdie som nie. Solve two bracket x minus one bracket equals ten.",
     "Hallo Katlego, ek verstaan nie hierdie som nie. Solve 2(x - 1) = 10"),
    ("v38", 8, "code-switch", "af", Q, "Ek sukkel met breuke. What is three over four divided by one half?",
     "Ek sukkel met breuke. What is 3/4 ÷ 1/2?"),
    ("v39", 8, "code-switch", "zu", A, "Ngicabanga ukuthi x equals five", "Ngicabanga ukuthi x = 5", P_EQ, "correct"),
    ("v40", 8, "code-switch", "st", A, "Ke nahana hore ke negative five", "Ke nahana hore ke -5", P_NEG, "correct"),
]


# The CAPS topic each spoken question belongs to (judged by hand against the seeded topic list).
TOPIC = {
         "v01": "Exponents",
         "v02": "Exponents",
         "v03": "Exponential and logarithmic functions",
         "v04": "Exponents",
         "v05": "Common Fractions",
         "v06": "Common Fractions",
         "v07": "Common Fractions",
         "v08": "Integers",
         "v09": "Integers",
         "v10": "Integers",
         "v11": "Algebraic Expressions",
         "v12": "Algebraic Equations",
         "v13": "Algebraic Expressions",
         "v14": "Algebraic Equations",
         "v15": "Algebraic Equations",
         "v16": "Polynomial functions",
         "v17": "Differential calculus",
         "v18": "Algebraic Equations",
         "v19": "Area and Perimeter",
         "v20": "Whole numbers",
         "v21": "Area and Perimeter",
         "v22": "Whole numbers",
         "v33": "Algebraic Equations",
         "v34": "Integers",
         "v35": "Common Fractions",
         "v36": "Algebraic Equations",
         "v37": "Algebraic Equations",
         "v38": "Common Fractions"}


def make_voice() -> None:
    (OUT / "voice").mkdir(parents=True, exist_ok=True)
    rows = []
    for vid, grade, cat, lang, role, said, typed, *rest in VOICE:
        base = {"id": vid, "grade": grade, "cat": cat, "lang": lang, "role": role, "said": said, "typed": typed}
        if role == A:
            base.update(problem=rest[0], verdict=rest[1])
        else:
            base["topic"] = TOPIC[vid]
        with tempfile.TemporaryDirectory() as tmp:
            aiff = f"{tmp}/a.aiff"
            subprocess.run(["say", "-v", "Tessa", "-r", "170", "-o", aiff, said], check=True)
            clean = OUT / "voice" / f"{vid}.ogg"
            # WhatsApp voice notes: Opus, mono, 16 kHz
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", aiff, "-ac", "1", "-ar", "16000",
                            "-c:a", "libopus", "-b:a", "16k", str(clean)], check=True)
            # the same note with street-level background noise and a cheap-phone band limit
            noisy = OUT / "voice" / f"{vid}_noisy.ogg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", aiff, "-f", "lavfi", "-i",
                            "anoisesrc=color=pink:amplitude=0.12:seed=7", "-filter_complex",
                            "[0:a]highpass=f=250,lowpass=f=3400,volume=0.8[v];"
                            "[v][1:a]amix=inputs=2:duration=first:normalize=0[m]",
                            "-map", "[m]", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "12k",
                            str(noisy)], check=True)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "csv=p=0", str(clean)], capture_output=True, text=True).stdout.strip())
        rows.append({**base, "file": f"voice/{vid}.ogg", "condition": "clean", "seconds": round(dur, 2)})
        rows.append({**base, "id": vid + "n", "file": f"voice/{vid}_noisy.ogg", "condition": "noisy",
                     "seconds": round(dur, 2)})
    (OUT / "voice.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"voice: {len(rows)} clips, {sum(r['seconds'] for r in rows) / 60:.1f} minutes")


# ── Photos ───────────────────────────────────────────────────────────────────
# Lines use a tiny markup: {2/3} is a stacked fraction, x^2 a raised power.
# type question: `problem` is what must be read.  working: `lines` as written,
# `wrong_line` the first wrong one (1-based, None = all correct).  diagram:
# `values` every label that must be read.  `answers`: final answers (leak check).
# `followups`: what the learner types next in the chat test (an attempt, then the answer).
PHOTOS = [
    dict(id="p01", followups=["x = 7", "x = 5"], grade=8, type="question", font="bradley", ink="blue", caption="",
         lines=["Solve for x:", "3x + 4 = 19"], problem="Solve for x: 3x + 4 = 19", keys=["3x+4=19"],
         answers=["x=5"]),
    dict(id="p02", followups=["3/7", "11/12"], grade=8, type="question", font="noteworthy", ink="black", caption="help me with this one",
         lines=["Calculate:", "{2/3} + {1/4}"], problem="Calculate: 2/3 + 1/4", keys=["2/3+1/4"], answers=["11/12"]),
    dict(id="p03", followups=["8a + 3b", "8a + b"], grade=8, type="question", font="marker", ink="pencil", caption="",
         lines=["Simplify:", "3a + 2b + 5a - b"], problem="Simplify: 3a + 2b + 5a - b", keys=["3a+2b+5a-b"],
         answers=["8a+b"]),
    dict(id="p04", followups=["x = 2 or x = -3", "x = 2 or x = 3"], grade=12, type="question", font="chalk", ink="blue", caption="",
         lines=["Solve for x:", "x^2 - 5x + 6 = 0"], problem="Solve for x: x^2 - 5x + 6 = 0", keys=["x^2-5x+6=0"],
         answers=["x=2", "x=3"]),
    dict(id="p05", followups=["3x^2", "3x^2 - 6"], grade=12, type="question", font="bradley", ink="black", caption="how do I do this?",
         lines=["Determine f '(x) if", "f(x) = x^3 - 6x"], problem="Determine f'(x) if f(x) = x^3 - 6x",
         keys=["f(x)=x^3-6x"], answers=["3x^2-6"]),
    dict(id="p06", followups=["-10", "0"], grade=8, type="question", font="comic", ink="blue", caption="",
         lines=["Calculate:", "-8 + 3 - (-5)"], problem="Calculate: -8 + 3 - (-5)", keys=["-8+3-(-5)"], answers=["0"]),

    dict(id="p07", followups=["2x = 8", "x = 4"], grade=8, type="working", font="bradley", ink="blue", caption="Where did I go wrong?",
         lines=["2x + 3 = 11", "2x = 11 + 3", "2x = 14", "x = 7"], problem="Solve 2x + 3 = 11", keys=["2x+3=11"],
         wrong_line=2, mistake="added 3 to the right side instead of subtracting it (2x should be 8, x = 4)",
         answers=["x=4"]),
    dict(id="p08", followups=["8/12 + 3/12", "11/12"], grade=8, type="working", font="noteworthy", ink="pencil", caption="is this right?",
         lines=["{2/3} + {1/4}", "= {3/7}"], problem="Calculate 2/3 + 1/4", keys=["2/3+1/4"], wrong_line=2,
         mistake="added the numerators and the denominators (answer should be 11/12)", answers=["11/12"]),
    dict(id="p09", followups=["3x + 12 = 21", "x = 3"], grade=8, type="working", font="marker", ink="black", caption="where is my mistake",
         lines=["3(x + 4) = 21", "3x + 4 = 21", "3x = 17", "x = {17/3}"], problem="Solve 3(x + 4) = 21", keys=["3(x+4)=21"],
         wrong_line=2, mistake="multiplied only the x by 3, not the 4 (should be 3x + 12 = 21, x = 3)",
         answers=["x=3"]),
    dict(id="p10", followups=["(x - 2)(x - 3) = 0", "x = 2 or x = 3"], grade=12, type="working", font="chalk", ink="blue", caption="Where did I go wrong?",
         lines=["x^2 - 5x + 6 = 0", "(x - 2)(x + 3) = 0", "x = 2  or  x = -3"], problem="Solve x^2 - 5x + 6 = 0",
         keys=["x^2-5x+6=0"], wrong_line=2,
         mistake="wrong sign in the second bracket: (x - 2)(x - 3), so x = 2 or x = 3", answers=["x=3"]),
    dict(id="p11", followups=["-3x + 6 = 9", "x = -1"], grade=8, type="working", font="comic", ink="blue", caption="I keep getting it wrong",
         lines=["-3(x - 2) = 9", "-3x - 6 = 9", "-3x = 15", "x = -5"], problem="Solve -3(x - 2) = 9", keys=["-3(x-2)=9"],
         wrong_line=2, mistake="-3 times -2 is +6, not -6 (should be -3x + 6 = 9, x = -1)", answers=["x=-1"]),
    dict(id="p12", followups=["ok thanks"], grade=8, type="working", font="bradley", ink="black", caption="is this right?",
         lines=["5x - 4 = 21", "5x = 25", "x = 5"], problem="Solve 5x - 4 = 21", keys=["5x-4=21"], wrong_line=None,
         mistake="none: the working is correct", answers=[]),

    dict(id="p13", followups=["x = 67", "x = 57"], grade=8, type="diagram", font="bradley", ink="blue", caption="", diagram="triangle_angles",
         lines=["Find x"], problem="Triangle with angles 52°, 71° and x. Find x.", values=["52", "71", "x"],
         answers=["57"]),
    dict(id="p14", followups=["11,5", "28 cm^2"], grade=8, type="diagram", font="noteworthy", ink="black", caption="find the area", diagram="rectangle",
         lines=["Area = ?"], problem="Rectangle 8 cm by 3,5 cm. Find the area.", values=["8", "3,5"],
         answers=["28"]),
    dict(id="p15", followups=["y = x^2 - 2x + 3", "y = x^2 - 2x - 3"], grade=12, type="diagram", font="chalk", ink="blue", caption="", diagram="parabola",
         lines=["Find the equation", "of the parabola"],
         problem="Parabola with x-intercepts (-1;0) and (3;0), y-intercept (0;-3) and turning point (1;-4). "
                 "Find its equation.",
         values=["(-1;0)", "(3;0)", "(0;-3)", "(1;-4)"], answers=["x^2-2x-3"]),
    dict(id="p16", followups=["4", "2"], grade=8, type="diagram", font="marker", ink="black", caption="", diagram="line",
         lines=["Find the gradient"], problem="Straight line through (0;2) and (4;10). Find the gradient.",
         values=["(0;2)", "(4;10)"], answers=["2"]),
    dict(id="p17", followups=["13", "14"], grade=8, type="diagram", font="comic", ink="blue", caption="what is the rule?", diagram="table",
         lines=["Find the rule and", "the missing value"],
         problem="Table: x = 1, 2, 3, 4 and y = 5, 8, 11, ?. Find the rule and the missing value.",
         values=["1", "2", "3", "4", "5", "8", "11"], answers=["14"]),
    dict(id="p18", followups=["x = 14", "x = 10"], grade=8, type="diagram", font="bradley", ink="pencil", caption="", diagram="right_triangle",
         lines=["Find x"], problem="Right-angled triangle with sides 6 cm and 8 cm and hypotenuse x. Find x.",
         values=["6", "8", "x"], answers=["10"]),
]

# The CAPS topics that are right for each page (judged by hand against the seeded topic list).
PHOTO_TOPICS = {"p01": ["Algebraic Equations"], "p02": ["Common Fractions"], "p03": ["Algebraic Expressions"], "p04": ["Polynomial functions"], "p05": ["Differential calculus"], "p06": ["Integers"], "p07": ["Algebraic Equations"], "p08": ["Common Fractions"], "p09": ["Algebraic Equations"], "p10": ["Polynomial functions"], "p11": ["Algebraic Equations"], "p12": ["Algebraic Equations"], "p13": ["Geometry of 2D Shapes", "Geometry of Straight Lines"], "p14": ["Area and Perimeter"], "p15": ["Functions and inverse functions", "Polynomial functions"], "p16": ["Graphs", "Functions and Relationships"], "p17": ["Functions and Relationships", "Numeric and Geometric Patterns"], "p18": ["Theorem of Pythagoras"]}

FONTS = {
    "bradley": "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "noteworthy": "/System/Library/Fonts/Noteworthy.ttc",
    "marker": "/System/Library/Fonts/MarkerFelt.ttc",
    "chalk": "/System/Library/Fonts/Supplemental/Chalkboard.ttc",
    "comic": "/System/Library/Fonts/Supplemental/Comic Sans MS.ttf",
}
INKS = {"blue": (28, 44, 130), "black": (30, 30, 34), "pencil": (88, 88, 92)}
W, H, RULE = 1200, 1600, 76  # WhatsApp standard quality: long side 1600 px


def _paper(rng):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (250, 247, 238))
    d = ImageDraw.Draw(img)
    for y in range(190, H, RULE):
        d.line([(0, y), (W, y)], fill=(170, 195, 225), width=2)
    d.line([(150, 0), (150, H)], fill=(225, 140, 140), width=3)
    return img


def _word(text, font, ink, rng):
    """One word on its own layer, tilted a little, so lines wobble like a hand."""
    from PIL import Image, ImageDraw
    box = font.getbbox(text)
    layer = Image.new("RGBA", (box[2] + 12, int(font.size * 1.5)), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((4, int(font.size * 0.15)), text, font=font, fill=ink + (255,))
    return layer.rotate(rng.uniform(-2.2, 2.2), expand=True, resample=Image.BICUBIC)


def _draw_line(img, text, x, y, font, small, ink, rng):
    """Draw one marked-up line with its baseline on the rule at `y`."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    for tok in re.findall(r"\{[^}]+\}|\S+", text):
        jy = rng.randint(-4, 4)
        if tok.startswith("{"):
            top, bot = tok[1:-1].split("/")
            wt, wb = small.getlength(top), small.getlength(bot)
            wide = int(max(wt, wb)) + 14
            for part, wpart, dy in ((top, wt, -small.size * 1.75), (bot, wb, -small.size * 0.72)):
                layer = _word(part, small, ink, rng)
                img.paste(layer, (int(x + (wide - wpart) / 2), int(y + dy + jy)), layer)
            d.line([(x, y - small.size * 0.62 + jy), (x + wide, y - small.size * 0.66 + jy)], fill=ink, width=4)
            x += wide + 20
            continue
        for i, piece in enumerate(re.split(r"\^(\w+)", tok)):
            if not piece:
                continue
            f = small if i % 2 else font
            layer = _word(piece, f, ink, rng)
            dy = -font.size * 1.5 if i % 2 else -font.size * 1.12
            img.paste(layer, (int(x), int(y + dy + jy)), layer)
            x += f.getlength(piece) + (2 if i % 2 == 0 else 6)
        x += font.size * 0.32
    return x


def _diagram(kind, ink, fontpath):
    """A hand-sketched figure (matplotlib's xkcd style) as a transparent image."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from PIL import Image
    font_manager.fontManager.addfont(fontpath)
    fam = font_manager.FontProperties(fname=fontpath).get_name()
    c = tuple(v / 255 for v in ink)
    with plt.xkcd(scale=1.2, length=120, randomness=3):
        plt.rcParams.update({"font.family": fam, "font.size": 22, "path.effects": []})
        fig, ax = plt.subplots(figsize=(8.4, 6.4), dpi=100)
        fig.patch.set_alpha(0)
        ax.set_facecolor((0, 0, 0, 0))
        if kind == "triangle_angles":
            ax.plot([0, 8, 2.6, 0], [0, 0, 5.2, 0], color=c, lw=3)
            for (x, y, s) in ((1.0, 0.35, "52°"), (6.6, 0.35, "71°"), (2.75, 4.1, "x")):
                ax.text(x, y, s, color=c, fontsize=30, ha="center")
            for (x, y, s) in ((-0.35, -0.3, "A"), (8.3, -0.3, "B"), (2.6, 5.45, "C")):
                ax.text(x, y, s, color=c, fontsize=26, ha="center")
            ax.axis("off"); ax.set_xlim(-1, 9); ax.set_ylim(-1, 6.2)
        elif kind == "rectangle":
            ax.plot([0, 8, 8, 0, 0], [0, 0, 3.5, 3.5, 0], color=c, lw=3)
            ax.text(4, -0.75, "8 cm", color=c, fontsize=30, ha="center")
            ax.text(8.25, 1.55, "3,5 cm", color=c, fontsize=30, ha="left")
            ax.axis("off"); ax.set_xlim(-1, 11.2); ax.set_ylim(-1.6, 4.6)
        elif kind == "right_triangle":
            ax.plot([0, 8, 0, 0], [0, 0, 6, 0], color=c, lw=3)
            ax.plot([0, 0.5, 0.5], [0.5, 0.5, 0], color=c, lw=2)
            ax.text(4, -0.8, "8 cm", color=c, fontsize=30, ha="center")
            ax.text(-0.3, 2.8, "6 cm", color=c, fontsize=30, ha="right")
            ax.text(4.5, 3.3, "x", color=c, fontsize=32)
            ax.axis("off"); ax.set_xlim(-2.6, 9); ax.set_ylim(-1.6, 6.8)
        elif kind in ("parabola", "line"):
            import numpy as np
            if kind == "parabola":
                xs = np.linspace(-2.2, 4.2, 80)
                ax.plot(xs, xs ** 2 - 2 * xs - 3, color=c, lw=3)
                pts = [(-1, 0, "(-1;0)", -1.05, 0.7), (3, 0, "(3;0)", 0.15, 0.7),
                       (0, -3, "(0;-3)", -1.5, -0.35), (1, -4, "(1;-4)", 0.05, -1.15)]
                ax.set_xlim(-3.4, 5.4); ax.set_ylim(-5.8, 6.5)
            else:
                xs = np.linspace(-1, 4.6, 20)
                ax.plot(xs, 2 * xs + 2, color=c, lw=3)
                pts = [(0, 2, "(0;2)", 0.25, -0.5), (4, 10, "(4;10)", -1.75, 0.25)]
                ax.set_xlim(-2, 6); ax.set_ylim(-2, 12.5)
            for px, py, s, dx, dy in pts:
                ax.plot([px], [py], "o", color=c, ms=9)
                ax.text(px + dx, py + dy, s, color=c, fontsize=26)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
            for sp in ("left", "bottom"):
                ax.spines[sp].set_position("zero"); ax.spines[sp].set_color(c)
            ax.set_xticks([]); ax.set_yticks([])
            ax.text(ax.get_xlim()[1] - 0.25, 0.3, "x", color=c, fontsize=26)
            ax.text(0.15, ax.get_ylim()[1] - 0.9, "y", color=c, fontsize=26)
        elif kind == "table":
            cells = [["x", "1", "2", "3", "4"], ["y", "5", "8", "11", "?"]]
            for r in range(3):
                ax.plot([0, 10], [r * 1.6, r * 1.6], color=c, lw=3)
            for k in range(6):
                ax.plot([k * 2, k * 2], [0, 3.2], color=c, lw=3)
            for r, row in enumerate(cells):
                for k, s in enumerate(row):
                    ax.text(k * 2 + 1, 3.2 - r * 1.6 - 1.05, s, color=c, fontsize=32, ha="center")
            ax.axis("off"); ax.set_xlim(-0.5, 10.5); ax.set_ylim(-1.6, 4.8)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", transparent=True)
        plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


def _camera(img, rng):
    """What a phone does to a page: tilt, uneven light, soft focus, grain, JPEG."""
    import numpy as np
    from PIL import Image, ImageFilter
    img = img.rotate(rng.uniform(-3.5, 3.5), resample=Image.BICUBIC, fillcolor=(232, 228, 216))
    a = np.asarray(img).astype("float32")
    yy, xx = np.mgrid[0:H, 0:W]
    cx, cy = rng.choice([(0, 0), (W, 0), (0, H), (W, H)])
    shade = 1.0 - 0.30 * (1 - np.hypot(xx - cx, yy - cy) / np.hypot(W, H))  # a shadow from one corner
    a = a * shade[..., None] * rng.uniform(0.9, 1.0)
    a += np.random.default_rng(rng.randint(0, 9999)).normal(0, 5, a.shape)
    out = Image.fromarray(a.clip(0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1.1))
    return out


def make_photos() -> None:
    from PIL import ImageFont
    (OUT / "photo").mkdir(parents=True, exist_ok=True)
    rows = []
    for p in PHOTOS:
        rng = random.Random(p["id"])
        ink, path = INKS[p["ink"]], FONTS[p["font"]]
        font, small = ImageFont.truetype(path, 78), ImageFont.truetype(path, 52)
        img = _paper(rng)
        y = 190 + RULE * 2
        x0 = 200 + rng.randint(-10, 30)
        if p.get("diagram"):
            for line in p["lines"]:
                _draw_line(img, line, x0, y, font, small, ink, rng)
                y += RULE * 2
            fig = _diagram(p["diagram"], ink, path)
            img.paste(fig, (190, y - RULE), fig)
        else:
            for n, line in enumerate(p["lines"]):
                _draw_line(img, line, x0 + (rng.randint(0, 24) if n else 0), y, font, small, ink, rng)
                y += RULE * 2
        _camera(img, rng).save(OUT / "photo" / f"{p['id']}.jpg", quality=72)
        row = {k: v for k, v in p.items() if k not in ("font", "ink", "diagram")}
        rows.append({**row, "topics": PHOTO_TOPICS[p["id"]], "file": f"photo/{p['id']}.jpg"})
    (OUT / "photo.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"photos: {len(rows)}")


def probe(set_: str) -> None:
    """Fill in `seconds` for a set's voice notes (the real set: ffprobe is not in the container)."""
    path = HERE / set_ / "voice.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for r in rows:
        r["seconds"] = round(float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
             str(HERE / set_ / r["file"])], capture_output=True, text=True).stdout.strip()), 2)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{set_}: {len(rows)} voice notes, {sum(r['seconds'] for r in rows) / len(rows):.1f}s on average")


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["--probe"]:
        probe(sys.argv[2])
    else:
        if sys.argv[1:2] != ["--photos"]:
            make_voice()
        make_photos()
