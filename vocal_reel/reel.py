#!/usr/bin/env python3
"""Reel « Le vocal de charge mentale » — Kiff ta Life.

Deux étapes, avec un seul fichier d'épisode (JSON) :

    python3 vocal_reel/reel.py transcrire episodes/marie.json
        -> transcrit le vocal et ta vidéo de réaction (avec minutage),
           et prépare les sous-titres à relire.

    python3 vocal_reel/reel.py monter episodes/marie.json
        -> fabrique le Reel 1080x1920 (MP4) + le fichier .srt.

Voir README.md pour le détail du fichier d'épisode.
"""
import json
import math
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ICI = Path(__file__).resolve().parent
POLICES = ICI / "fonts"

W, H, FPS = 1080, 1920, 30
ZONE_HAUT, ZONE_BAS = 250, 350          # zones cachées par l'interface Instagram
MARGE = 60

BORDEAUX = (139, 10, 30)
FRAMBOISE = (170, 27, 56)
ROSE_BONBON = (234, 147, 177)
ROSE_PALE = (244, 195, 212)
CREME = (243, 235, 221)
CACAO = (58, 10, 18)

# styles de sous-titres : la voix de la maman, et ta voix à la fin
# sous-titres sobres : fond crème, texte cacao, mot en cours simplement écrit en bordeaux
# ("actif" = couleur d'un surlignage derrière le mot ; None = pas de surlignage)
STYLE_VOCAL = {"fond": CREME, "texte": CACAO, "actif": None, "actif_texte": BORDEAUX}
STYLE_MOI = {"fond": CREME, "texte": CACAO, "actif": None, "actif_texte": BORDEAUX}


# ---------------------------------------------------------------- utilitaires

def police(nom, taille):
    return ImageFont.truetype(str(POLICES / nom), taille)


def lancer(cmd):
    subprocess.run(cmd, check=True)


def duree(fichier):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(fichier)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def charger_episode(chemin):
    chemin = Path(chemin).resolve()
    ep = json.loads(chemin.read_text(encoding="utf-8"))
    base = chemin.parent
    for cle in ("reaction", "vocal"):
        ep[cle] = str((base / ep[cle]).resolve())
    nom = re.sub(r"[^a-z0-9]+", "-", ep.get("titre", ep["prenom"]).lower()).strip("-")
    ep["dossier"] = (base / ep.get("sortie", "sortie") / nom).resolve()
    ep["dossier"].mkdir(parents=True, exist_ok=True)
    ep["nom"] = nom
    return ep


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def horodatage_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ---------------------------------------------------------------- transcription

def wav_mono(src, dst, debut=None, fin=None):
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if debut is not None:
        cmd += ["-ss", str(debut)]
    if fin is not None:
        cmd += ["-to", str(fin)]
    lancer(cmd + ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dst)])


def lire_wav(chemin):
    with wave.open(str(chemin)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        return a, w.getframerate()


def transcrire_fichier(wav, modele):
    from faster_whisper import WhisperModel
    audio, _ = lire_wav(wav)
    m = WhisperModel(modele, compute_type="int8")
    segs, _ = m.transcribe(audio, language="fr", word_timestamps=True, vad_filter=True)
    mots = []
    for s in segs:
        for w in s.words:
            mot = w.word.strip()
            if not mot:
                continue
            # Whisper coupe « c'est » en « c » + « 'est » : on recolle
            if mots and (mot[0] in "'’-" or mots[-1]["mot"][-1] in "'’"):
                mots[-1]["mot"] += mot
                mots[-1]["fin"] = round(w.end, 2)
                continue
            mots.append({"mot": mot, "debut": round(w.start, 2), "fin": round(w.end, 2)})
    return mots


PETITS_MOTS = {"de", "la", "le", "les", "un", "une", "des", "du", "à", "au", "aux", "et", "ou", "mais",
               "pour", "par", "sur", "dans", "en", "que", "qui", "ce", "ces", "mon", "ma", "mes", "ton", "ta",
               "tes", "son", "sa", "ses", "il", "elle", "ils", "je", "tu", "on", "nous", "vous", "ne", "pas", "si"}


def recoller_ponctuation(mots):
    res = []
    for m in mots:
        if res and re.fullmatch(r"[.!?…,;:»]+", m["mot"]):
            # typographie française : espace fine avant ! ? ; :
            esp = "\u202f" if m["mot"][0] in "!?;:»" else ""
            res[-1] = dict(res[-1], mot=res[-1]["mot"] + esp + m["mot"], fin=m["fin"])
        else:
            res.append(dict(m))
    return res


def grouper(mots, mini=3, maxi=5, max_car=30):
    """Petits groupes de 3 à 5 mots, coupés de préférence à la ponctuation ou aux pauses,
    jamais juste après un petit mot (« de la / soirée »)."""
    mots = recoller_ponctuation(mots)
    groupes, cour = [], []
    for i, m in enumerate(mots):
        cour.append(m)
        suivant = mots[i + 1] if i + 1 < len(mots) else None
        pause = suivant is not None and suivant["debut"] - m["fin"] > 0.5
        fin_phrase = m["mot"][-1] in ".!?…"
        ponct = m["mot"][-1] in ".!?…,;:"
        longueur = len(" ".join(x["mot"] for x in cour))
        if suivant is None or fin_phrase or pause or (len(cour) >= mini and ponct):
            groupes.append(cour)
            cour = []
        elif (len(cour) >= maxi or longueur >= max_car) and not (
                len(cour) <= maxi and suivant["mot"][-1] in ".!?…" and not pause):
            # (on accepte un mot de plus pour ne pas laisser un « faut. » tout seul)
            # on reporte les petits mots de fin sur le groupe suivant
            report = []
            while len(cour) > 2 and cour[-1]["mot"].lower().strip(",") in PETITS_MOTS:
                report.insert(0, cour.pop())
            groupes.append(cour)
            cour = report
    if cour:
        groupes.append(cour)
    return groupes


def ecrire_sous_titres_txt(groupes, chemin, entete):
    lignes = [entete, ""]
    for g in groupes:
        texte = " ".join(m["mot"] for m in g)
        lignes.append(f"{g[0]['debut']:7.2f} | {g[-1]['fin']:7.2f} | {texte}")
    Path(chemin).write_text("\n".join(lignes) + "\n", encoding="utf-8")


def lire_sous_titres_txt(chemin, mots):
    """Relit le fichier corrigé à la main. Les mots gardent leur minutage d'origine
    quand leur nombre n'a pas changé ; sinon on répartit le temps selon la longueur."""
    groupes = []
    for ligne in Path(chemin).read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\s*\d", ligne):
            continue
        d, f, texte = [x.strip() for x in ligne.split("|", 2)]
        d, f = float(d), float(f)
        nouveaux = texte.split()
        anciens = [m for m in mots if m["debut"] >= d - 0.01 and m["fin"] <= f + 0.01]
        if len(anciens) == len(nouveaux):
            g = [{"mot": n, "debut": a["debut"], "fin": a["fin"]} for n, a in zip(nouveaux, anciens)]
        else:
            total = sum(len(n) for n in nouveaux) or 1
            t, g = d, []
            for n in nouveaux:
                dt = (f - d) * len(n) / total
                g.append({"mot": n, "debut": t, "fin": t + dt})
                t += dt
        groupes.append(g)
    return groupes


def etape_transcrire(ep):
    dos = ep["dossier"]
    modele = ep.get("modele_whisper", "medium")

    wav_mono(ep["vocal"], dos / "vocal.wav")
    mots = transcrire_fichier(dos / "vocal.wav", modele)
    (dos / "vocal_mots.json").write_text(json.dumps(mots, ensure_ascii=False, indent=1), encoding="utf-8")

    # transcription lisible, phrase par phrase, pour choisir le passage et l'accroche
    phrases, cour = [], []
    for m in mots:
        cour.append(m)
        if m["mot"][-1] in ".!?…":
            phrases.append(cour)
            cour = []
    if cour:
        phrases.append(cour)
    txt = [f"Vocal de {ep['prenom']} — durée {mmss(duree(ep['vocal']))}", ""]
    for p in phrases:
        txt.append(f"[{p[0]['debut']:6.2f} → {p[-1]['fin']:6.2f}]  " + " ".join(m["mot"] for m in p))
    (dos / "vocal_transcription.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    ecrire_sous_titres_txt(grouper(mots), dos / "sous_titres_vocal.txt",
                           "# Sous-titres du vocal : début | fin | texte. Corrige le texte, garde les temps.")

    wav_mono(ep["reaction"], dos / "reaction.wav")
    mots_r = transcrire_fichier(dos / "reaction.wav", modele)
    (dos / "reaction_mots.json").write_text(json.dumps(mots_r, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = [f"Ta vidéo de réaction — durée {mmss(duree(ep['reaction']))}", ""]
    for g in grouper(mots_r, 6, 14, 90):
        txt.append(f"[{g[0]['debut']:6.2f} → {g[-1]['fin']:6.2f}]  " + " ".join(m["mot"] for m in g))
    (dos / "reaction_transcription.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    ecrire_sous_titres_txt(grouper(mots_r), dos / "sous_titres_reaction.txt",
                           "# Sous-titres de ta vidéo : début | fin | texte. Corrige le texte, garde les temps.")

    print((dos / "vocal_transcription.txt").read_text(encoding="utf-8"))
    print((dos / "reaction_transcription.txt").read_text(encoding="utf-8"))
    print(f"Fichiers dans : {dos}")


# ---------------------------------------------------------------- son

def nettoyer_son(src, dst, debut, fin, debruitage):
    """Voix nettoyée légèrement, volume normalisé, jamais accélérée."""
    filtres = ["highpass=f=80", "lowpass=f=12000"]
    if debruitage:
        filtres.append(f"afftdn=nr={debruitage}:nf=-40")
    filtres += ["loudnorm=I=-16:TP=-1.5:LRA=11", "aresample=48000",
                "afade=t=in:d=0.03", f"afade=t=out:st={max(0, fin - debut - 0.05):.3f}:d=0.05"]
    lancer(["ffmpeg", "-v", "error", "-y", "-ss", str(debut), "-to", str(fin), "-i", str(src),
            "-vn", "-ac", "2", "-af", ",".join(filtres), str(dst)])


def enveloppe(wav_chemin, pas):
    a, sr = lire_wav(wav_chemin)
    n = max(1, int(sr * pas))
    k = len(a) // n
    rms = np.sqrt((a[:k * n].reshape(k, n) ** 2).mean(axis=1) + 1e-9)
    return rms / (rms.max() or 1)


# ---------------------------------------------------------------- dessin

def emoji_police():
    for p in ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
              "/usr/share/fonts/noto/NotoColorEmoji.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, 109)
    return None


EMOJI = emoji_police()
RE_EMOJI = re.compile("([\U0001F000-\U0001FAFF☀-➿]️?)")


def texte_avec_emoji(draw_img, xy, texte, ft, couleur):
    """Écrit un texte qui peut contenir des emojis (en couleur). Renvoie la largeur."""
    x, y = xy
    d = ImageDraw.Draw(draw_img) if draw_img is not None else None
    taille = ft.size
    for morceau in RE_EMOJI.split(texte):
        if not morceau:
            continue
        if RE_EMOJI.fullmatch(morceau):
            if EMOJI is None:
                continue
            e = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
            ImageDraw.Draw(e).text((0, 0), morceau, font=EMOJI, embedded_color=True)
            e = e.crop(e.getbbox() or (0, 0, 1, 1))
            h = int(taille * 0.95)
            e = e.resize((max(1, int(e.width * h / e.height)), h), Image.LANCZOS)
            x += taille * 0.15                  # petit espace avant l'emoji
            if draw_img is not None and couleur is not None:
                draw_img.alpha_composite(e, (int(x), int(y + taille * 0.12)))
            x += e.width + taille * 0.1
        else:
            if couleur is not None:
                d.text((x, y), morceau, font=ft, fill=couleur)
            x += ft.getlength(morceau)
    return x - xy[0]


def pilule(img, box, rayon, couleur):
    ImageDraw.Draw(img).rounded_rectangle(box, rayon, fill=couleur)


def ombre(img, box, rayon, force=70, flou=18):
    """Ombre douce sous un élément (calculée seulement autour de lui, pour aller vite)."""
    x0, y0, x1, y1 = [int(v) for v in box]
    pad = flou * 3
    calque = Image.new("RGBA", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(calque).rounded_rectangle((pad, pad + 8, pad + x1 - x0, pad + y1 - y0 + 8), rayon,
                                             fill=(58, 10, 18, force))
    calque = calque.filter(ImageFilter.GaussianBlur(flou))
    dx, dy = x0 - pad, y0 - pad
    calque = calque.crop((max(0, -dx), max(0, -dy), min(calque.width, img.width - dx), min(calque.height, img.height - dy)))
    img.alpha_composite(calque, (max(0, dx), max(0, dy)))


class Bulle:
    """Bulle façon message vocal (sans logo) : bouton lecture, onde, prénom, durée."""
    def __init__(self, prenom, env_barres, duree_totale):
        self.prenom, self.env, self.total = prenom, env_barres, duree_totale
        self.x0, self.y0, self.x1, self.y1 = MARGE + 20, ZONE_HAUT + 20, W - MARGE - 20, ZONE_HAUT + 200
        self.f_nom = police("DMSans-Bold.ttf", 40)
        self.f_temps = police("DMSans-Medium.ttf", 32)

    def dessiner(self, img, t, niveau, alpha=1.0):
        calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
        x0, y0, x1, y1 = self.x0, self.y0, self.x1, self.y1
        ombre(calque, (x0, y0, x1, y1), 50, 60)
        pilule(calque, (x0, y0, x1, y1), 50, ROSE_PALE + (255,))
        d = ImageDraw.Draw(calque)
        # bouton (pause pendant la lecture)
        cx, cy, r = x0 + 95, (y0 + y1) // 2, 58
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BORDEAUX)
        d.rounded_rectangle((cx - 20, cy - 24, cx - 6, cy + 24), 4, fill=ROSE_PALE)
        d.rounded_rectangle((cx + 6, cy - 24, cx + 20, cy + 24), 4, fill=ROSE_PALE)
        # prénom
        d.text((x0 + 180, y0 + 24), self.prenom, font=self.f_nom, fill=BORDEAUX)
        # onde : forme du vocal, partie écoutée pleine, la barre en cours bouge avec le son
        ox0, ox1, oy = x0 + 180, x1 - 50, y0 + 118
        n = len(self.env)
        pas = (ox1 - ox0) / n
        prog = min(1.0, t / self.total) if self.total else 1
        for i, v in enumerate(self.env):
            frac = i / n
            h = 8 + 52 * v
            if abs(frac - prog) < 1.5 / n:
                h = 8 + 52 * max(v, niveau)
            x = ox0 + i * pas
            coul = BORDEAUX + (255,) if frac <= prog else BORDEAUX + (95,)
            d.rounded_rectangle((x, oy - h / 2, x + pas * 0.55, oy + h / 2), 3, fill=coul)
        px = ox0 + prog * (ox1 - ox0)
        d.ellipse((px - 13, oy - 13, px + 13, oy + 13), fill=FRAMBOISE)
        # durée
        temps = f"{mmss(t)} / {mmss(self.total)}"
        tw = self.f_temps.getlength(temps)
        d.text((x1 - 50 - tw, y0 + 28), temps, font=self.f_temps, fill=BORDEAUX)
        if alpha < 1:
            calque.putalpha(calque.getchannel("A").point(lambda a: int(a * alpha)))
        img.alpha_composite(calque)

    @property
    def bas(self):
        return self.y1 + 20


class SousTitres:
    """Petits groupes de mots dans une pilule, mot en cours surligné."""
    def __init__(self, groupes, style, taille=74):
        self.groupes, self.style = groupes, style
        self.ft = police("DMSans-Bold.ttf", taille)
        self.lh = int(taille * 1.32)
        self.esp = self.ft.getlength(" ")

    def groupe_a(self, t):
        trouve = None
        for g in self.groupes:              # le dernier groupe commencé gagne
            if g[0]["debut"] - 0.05 <= t < g[-1]["fin"] + 0.25:
                trouve = g
        return trouve

    def largeur(self, l):
        return sum(self.ft.getlength(m["mot"]) for m in l) + self.esp * (len(l) - 1)

    def lignes(self, g):
        """Une ligne si ça tient, sinon deux lignes équilibrées (pas de mot tout seul)."""
        maxw = W - 2 * MARGE - 80
        if self.largeur(g) <= maxw or len(g) < 2:
            return [g]
        coupes = [(max(self.largeur(g[:i]), self.largeur(g[i:])), i) for i in range(1, len(g))]
        _, i = min(coupes)
        return [g[:i], g[i:]]

    def hauteur(self, g):
        return len(self.lignes(g)) * self.lh + 44

    def dessiner(self, img, t, g, y_centre):
        ls = self.lignes(g)
        hh = len(ls) * self.lh + 44
        largeurs = [self.largeur(l) for l in ls]
        bw = max(largeurs) + 80
        x0, y0 = (W - bw) / 2, y_centre - hh / 2
        calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ombre(calque, (x0, y0, x0 + bw, y0 + hh), 34)
        pilule(calque, (x0, y0, x0 + bw, y0 + hh), 34, self.style["fond"] + (255,))
        d = ImageDraw.Draw(calque)
        asc = self.ft.getbbox("Hg")[1]
        for li, l in enumerate(ls):
            x = (W - largeurs[li]) / 2
            y = y0 + 22 + li * self.lh
            for m in l:
                lw = self.ft.getlength(m["mot"])
                actif = m["debut"] <= t < m["fin"] + 0.08
                if actif and self.style["actif"]:
                    d.rounded_rectangle((x - 12, y + 4, x + lw + 12, y + self.lh - 8), 18,
                                        fill=self.style["actif"] + (255,))
                d.text((x, y + (self.lh - self.ft.size) / 2 - asc / 2), m["mot"], font=self.ft,
                       fill=(self.style["actif_texte"] if actif else self.style["texte"]) + (255,))
                x += lw + self.esp
        img.alpha_composite(calque)


def lignes_accroche(texte, ft):
    mots, lignes, cour = texte.upper().split(), [], ""
    for m in mots:
        essai = (cour + " " + m).strip()
        if ft.getlength(essai) > W - 2 * MARGE - 60 and cour:
            lignes.append(cour)
            cour = m
        else:
            cour = essai
    lignes.append(cour)
    return lignes


def hauteur_accroche(texte):
    ft = police("Anton-Regular.ttf", 100)
    return len(lignes_accroche(texte, ft)) * int(ft.size * 1.12) + 60


def accroche(img, texte, t, duree_acc, y_centre):
    """Bandeau d'accroche : la phrase forte en gros, Anton majuscules, placé hors du visage."""
    ft = police("Anton-Regular.ttf", 100)
    lignes = lignes_accroche(texte, ft)
    lh = int(ft.size * 1.12)
    hh = len(lignes) * lh + 60
    entree = min(1.0, t / 0.18)
    sortie = min(1.0, max(0.0, (duree_acc - t) / 0.18))
    a = min(entree, sortie)
    y0 = y_centre - hh / 2 + (1 - entree) * 40
    calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ombre(calque, (0, y0, W, y0 + hh), 0, 90, 24)
    ImageDraw.Draw(calque).rectangle((0, y0, W, y0 + hh), fill=BORDEAUX + (255,))
    d = ImageDraw.Draw(calque)
    for i, l in enumerate(lignes):
        lw = ft.getlength(l)
        d.text(((W - lw) / 2, y0 + 24 + i * lh), l, font=ft, fill=CREME)
    if a < 1:
        calque.putalpha(calque.getchannel("A").point(lambda v: int(v * a)))
    img.alpha_composite(calque)


HAUTEUR_CTA = 120
ECART_CTA = 24


def hauteur_cta(textes):
    return len(textes) * (HAUTEUR_CTA + ECART_CTA)


def appel_action(img, textes, t, delai=0.7):
    """Cartes de fin aérées, textes pas trop gros, au-dessus de la zone basse.
    La première en bordeaux, les suivantes en crème ; elles arrivent l'une après l'autre."""
    ft = police("DMSans-Bold.ttf", 50)
    y_bas = H - ZONE_BAS - 30
    for i, texte in reversed(list(enumerate(textes))):
        ti = t - i * delai
        y_bas_i = y_bas - (len(textes) - 1 - i) * (HAUTEUR_CTA + ECART_CTA)
        if ti < 0:
            continue
        fond, coul = (BORDEAUX, CREME) if i == 0 else (CREME, BORDEAUX)
        largeur = texte_avec_emoji(None, (0, 0), texte, ft, None)
        bw, hh = largeur + 120, HAUTEUR_CTA
        a = min(1.0, ti / 0.3)
        x0, y0 = (W - bw) / 2, y_bas_i - hh + (1 - a) * 30
        calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ombre(calque, (x0, y0, x0 + bw, y0 + hh), 60, 70)
        pilule(calque, (x0, y0, x0 + bw, y0 + hh), 60, fond + (255,))
        texte_avec_emoji(calque, (x0 + 55, y0 + (hh - 50) / 2 - 9), texte, ft, coul + (255,))
        if a < 1:
            calque.putalpha(calque.getchannel("A").point(lambda v: int(v * a)))
        img.alpha_composite(calque)


# ---------------------------------------------------------------- visage

def visages(src, debut, fin, fps=5):
    """Repère ton visage (rectangles en pixels du cadre final) pour ne pas le couvrir."""
    import cv2
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    lw, lh = W // 4, H // 4
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", str(debut), "-to", str(fin), "-i", str(src),
                          "-vf", f"scale={lw}:{lh}:force_original_aspect_ratio=increase,crop={lw}:{lh},fps={fps}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    res, i = [], 0
    while True:
        buf = p.stdout.read(lw * lh)
        if len(buf) < lw * lh:
            break
        g = np.frombuffer(buf, np.uint8).reshape(lh, lw)
        fs = det.detectMultiScale(g, 1.1, 5, minSize=(24, 24))
        boites = [(x * 4, y * 4, (x + w) * 4, (y + h) * 4) for x, y, w, h in fs]
        res.append((i / fps, max(boites, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if boites else None))
        i += 1
    p.wait()
    return res


def position_sous_titre(boites, t0, t1, hauteur, haut_min, bas_max):
    """Centre de l'écran par défaut ; si ça touche le visage, on passe dessous (ou dessus)."""
    y_def = H * 0.5
    zone = [b for (t, b) in boites if t0 - 0.2 <= t <= t1 + 0.2 and b]
    if not zone:
        return y_def
    fy0 = min(b[1] for b in zone) - 30
    fy1 = max(b[3] + (b[3] - b[1]) * 0.15 for b in zone) + 30     # le menton dépasse souvent du cadre détecté
    if y_def + hauteur / 2 < fy0 or y_def - hauteur / 2 > fy1:
        return y_def
    if fy1 + hauteur + 10 <= bas_max:
        return fy1 + hauteur / 2 + 10
    if fy0 - hauteur - 10 >= haut_min:
        return fy0 - hauteur / 2 - 10
    return bas_max - hauteur / 2       # pas de place : le plus bas possible, hors zone Instagram


# ---------------------------------------------------------------- montage

def etape_monter(ep):
    dos = ep["dossier"]
    mots_v = json.loads((dos / "vocal_mots.json").read_text(encoding="utf-8"))
    mots_r = json.loads((dos / "reaction_mots.json").read_text(encoding="utf-8"))
    debruitage = ep.get("debruitage", 8)

    ext = ep["vocal_extrait"]
    acc = ep["accroche"]
    fin = ep["fin"]
    # tes réactions pendant le vocal : un seul passage continu, ou plusieurs plans mis bout à bout
    rpv = ep.get("reaction_pendant_vocal", {"debut": 0.0})
    plans_reaction = rpv if isinstance(rpv, list) else [rpv]

    # 1. le son : [accroche (phrase du vocal)] + [extrait du vocal] + [ta phrase de fin]
    morceaux = []
    if acc.get("debut") is not None:
        nettoyer_son(ep["vocal"], dos / "a_accroche.wav", acc["debut"], acc["fin"], debruitage)
        morceaux.append(("vocal", acc["debut"], acc["fin"], dos / "a_accroche.wav"))
    nettoyer_son(ep["vocal"], dos / "a_vocal.wav", ext["debut"], ext["fin"], debruitage)
    morceaux.append(("vocal", ext["debut"], ext["fin"], dos / "a_vocal.wav"))
    plans_fin = fin if isinstance(fin, list) else [fin]
    for i, p in enumerate(plans_fin):
        wav = dos / f"a_fin{i}.wav"
        if p.get("son", True):
            nettoyer_son(ep["reaction"], wav, p["debut"], p["fin"], ep.get("debruitage_fin", 6))
        else:                                   # plan muet (pour laisser lire l'appel à l'action)
            lancer(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{p['fin'] - p['debut']:.3f}", str(wav)])
        morceaux.append(("moi" if p.get("son", True) else "muet", p["debut"], p["fin"], wav))

    liste = dos / "a_liste.txt"
    liste.write_text("".join(f"file '{m[3]}'\n" for m in morceaux))
    lancer(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(liste),
            "-c:a", "pcm_s16le", str(dos / "a_total.wav")])

    # 2. chronologie : chaque mot reçoit son temps dans le Reel final
    t, chrono = 0.0, []
    for src, d, f, _ in morceaux:
        chrono.append((src, d, f, t))
        t += f - d
    total = t
    duree_acc = (acc["fin"] - acc["debut"]) if acc.get("debut") is not None else acc.get("duree", 2.0)
    duree_vocal = sum(f - d for s, d, f, _ in chrono if s == "vocal")
    debut_fin = next(c[3] for c in chrono if c[0] != "vocal")
    ctas = ep.get("cta", "Envoie-moi ton vocal en DM 🎙️")
    ctas = ctas if isinstance(ctas, list) else [ctas]

    def placer(groupes, src, d, f, decal):
        res = []
        for g in groupes:
            g2 = [{"mot": m["mot"], "debut": m["debut"] - d + decal, "fin": m["fin"] - d + decal}
                  for m in g if m["debut"] >= d - 0.05 and m["fin"] <= f + 0.15]
            if g2:
                res.append(g2)
        return res

    g_vocal_tous = lire_sous_titres_txt(dos / "sous_titres_vocal.txt", mots_v)
    g_moi_tous = lire_sous_titres_txt(dos / "sous_titres_reaction.txt", mots_r)
    g_vocal, g_moi, g_srt = [], [], []
    for src, d, f, decal in chrono:
        if src == "vocal":
            gs = placer(g_vocal_tous, src, d, f, decal)
            g_srt += gs
            if decal + 0.01 >= duree_acc:       # pas de sous-titres sous le bandeau d'accroche
                g_vocal += gs
            else:
                g_vocal += [g for g in gs if g[-1]["fin"] > duree_acc + 0.2]
        elif src == "moi":
            gs = placer(g_moi_tous, src, d, f, decal)
            g_moi += gs
            g_srt += gs

    # 3. le .srt séparé
    srt = []
    for i, g in enumerate(g_srt, 1):
        fin_g = g[-1]["fin"] + 0.2
        if i < len(g_srt):
            fin_g = min(fin_g, g_srt[i][0]["debut"])
        srt += [str(i), f"{horodatage_srt(g[0]['debut'])} --> {horodatage_srt(fin_g)}",
                " ".join(m["mot"] for m in g), ""]
    (dos / f"{ep['nom']}.srt").write_text("\n".join(srt), encoding="utf-8")

    # 4. l'onde de la bulle
    env_fin = enveloppe(dos / "a_total.wav", 1 / FPS)
    nb_barres = 34
    env_v = env_fin[: int(duree_vocal * FPS)]
    barres = np.array([c.mean() for c in np.array_split(env_v, nb_barres)]) if len(env_v) else np.zeros(nb_barres)
    barres = np.clip(barres / (barres.max() or 1), 0.08, 1)
    bulle = Bulle(ep["prenom"], barres, duree_vocal)

    # 5. visage : où poser les sous-titres
    plans = []                               # (début dans ta vidéo, fin, position dans le Reel)
    reste, decal = duree_vocal, 0.0
    for i, p in enumerate(plans_reaction):
        d = p["debut"]
        f = p.get("fin", d + reste) if i < len(plans_reaction) - 1 else d + reste
        f = min(f, d + reste)
        plans.append((d, f, decal))
        reste -= f - d
        decal += f - d
        if reste <= 0.01:
            break
    bx_vocal = []
    for d, f, decal in plans:
        bx_vocal += [(tt + decal, b) for tt, b in visages(ep["reaction"], d, f)]
    bx_fin = []
    for src, d, f, decal in chrono:
        if src != "vocal":
            bx_fin += [(tt + decal, b) for tt, b in visages(ep["reaction"], d, f)]
    st_v = SousTitres(g_vocal, STYLE_VOCAL)
    st_m = SousTitres(g_moi, STYLE_MOI)
    pos = {}
    for g in g_vocal:
        h = st_v.hauteur(g)
        pos[id(g)] = position_sous_titre(bx_vocal, g[0]["debut"], g[-1]["fin"], h, bulle.bas + 20, H - ZONE_BAS - 20)
    for g in g_moi:
        h = st_m.hauteur(g)
        pos[id(g)] = position_sous_titre(bx_fin, g[0]["debut"], g[-1]["fin"], h, ZONE_HAUT + 20,
                                         H - ZONE_BAS - 30 - hauteur_cta(ctas) - 20)

    y_accroche = position_sous_titre(bx_vocal, 0, duree_acc, hauteur_accroche(acc["texte"]),
                                     bulle.bas + 20, H - ZONE_BAS - 20)

    # 6. l'image, image par image
    sortie = dos / f"{ep['nom']}.mp4"
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(dos / "a_total.wav"),
                            "-c:v", "libx264", "-preset", ep.get("preset", "medium"), "-crf", str(ep.get("crf", 19)),
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                            "-shortest", "-movflags", "+faststart", str(sortie)], stdin=subprocess.PIPE)
    plans += [(d, f, decal) for src, d, f, decal in chrono if src != "vocal"]
    n_total = int(round(total * FPS))
    n = 0
    for (d, f, decal) in plans:
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", str(d), "-to", str(f), "-i", ep["reaction"],
                                "-vf", vf, "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        nb_plan = int(round((f - d) * FPS))
        derniere = None
        for k in range(nb_plan):
            buf = dec.stdout.read(W * H * 3)
            if len(buf) == W * H * 3:
                derniere = buf
            elif derniere is None:
                break
            t = n / FPS
            img = Image.frombuffer("RGB", (W, H), derniere).convert("RGBA")
            niveau = float(env_fin[min(n, len(env_fin) - 1)])
            if t < debut_fin:
                bulle.dessiner(img, t, niveau)
                g = st_v.groupe_a(t)
                if g and t >= duree_acc - 0.1:
                    st_v.dessiner(img, t, g, pos[id(g)])
                if t < duree_acc:
                    accroche(img, acc["texte"], t, duree_acc, y_accroche)
            else:
                tf = t - debut_fin
                if tf < 0.3:
                    bulle.dessiner(img, duree_vocal, 0, 1 - tf / 0.3)
                g = st_m.groupe_a(t)
                if g:
                    st_m.dessiner(img, t, g, pos[id(g)])
                cta_debut = ep.get("cta_apres", 0.6)
                if tf >= cta_debut:
                    appel_action(img, ctas, tf - cta_debut)
            enc.stdin.write(img.convert("RGB").tobytes())
            n += 1
        dec.stdout.close()
        dec.wait()
    enc.stdin.close()
    enc.wait()
    print(f"Reel : {sortie} ({total:.1f} s, {n}/{n_total} images)")
    print(f"Sous-titres : {dos / (ep['nom'] + '.srt')}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("transcrire", "monter"):
        print(__doc__)
        sys.exit(1)
    episode = charger_episode(sys.argv[2])
    (etape_transcrire if sys.argv[1] == "transcrire" else etape_monter)(episode)
