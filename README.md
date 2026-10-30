# Kiff ta Life · Reel « Le vocal de charge mentale »

Une maman envoie un vocal, tu filmes ta réaction, et l'outil fabrique le Reel :
accroche, bulle « vocal » animée, sous-titres, ta phrase de fin et l'appel à l'action.

## Installer (une seule fois)

```
sudo apt install ffmpeg
pip install -r requirements.txt
```

## Un nouvel épisode, en 3 étapes

1. **Copie** `episodes/exemple.json`, puis change les fichiers, le prénom, le titre et l'accroche.
2. **Transcris** :
   ```
   python3 vocal_reel/reel.py transcrire episodes/mon-episode.json
   ```
   Ça crée, dans `sortie/<titre>/` :
   - `vocal_transcription.txt` et `reaction_transcription.txt` : le texte avec le minutage, pour choisir les passages ;
   - `sous_titres_vocal.txt` et `sous_titres_reaction.txt` : les sous-titres à relire. Corrige le texte, mais ne touche pas aux temps.
3. **Remplis les temps** dans le fichier d'épisode, puis monte :
   ```
   python3 vocal_reel/reel.py monter episodes/mon-episode.json
   ```
   Résultat : `sortie/<titre>/<titre>.mp4` (1080x1920, 30 i/s, H.264 + AAC) et `<titre>.srt`.

## Le fichier d'épisode

| Champ | Ce que c'est |
| --- | --- |
| `prenom` | Prénom affiché dans la bulle vocal |
| `titre` | Sert au nom des fichiers |
| `reaction`, `vocal` | Tes deux fichiers (chemins depuis le fichier d'épisode) |
| `accroche.texte` | La phrase forte en gros au début (Anton, majuscules) |
| `accroche.debut` / `fin` | Facultatif : rejoue ce passage du vocal pendant l'accroche. Sinon, laisse `null` et mets `duree` |
| `vocal_extrait` | Le passage du vocal à garder (en secondes), ou une liste de passages mis bout à bout pour couper une hésitation |
| `reaction_pendant_vocal` | Tes réactions pendant le vocal : de préférence un seul passage continu `{"debut": 17}` (plus naturel), ou plusieurs plans mis bout à bout |
| `fin` | Le passage de ta vidéo où tu parles à la fin. Ou plusieurs plans, dont des plans muets (`"son": false`) pour laisser le temps de lire l'appel à l'action |
| `cta` | L'appel à l'action à l'écran : un texte, ou une liste de cartes qui arrivent l'une après l'autre (les emojis marchent) |
| `cta_apres` | Quand les cartes apparaissent, en secondes après le début de ta fin |
| `debruitage` | Réduction de bruit du vocal (0 = aucune, 8 = léger, 15 = fort) |

## Ce que fait l'outil

- **Son.** Le vocal est nettoyé légèrement (sans effet métallique, jamais accéléré) et mis à un volume normalisé. Le son de ta vidéo est coupé pendant le vocal, puis remis pour ta fin.
- **Sous-titres.** Par groupes de 3 à 5 mots, sur fond crème, texte cacao, le mot en cours écrit en bordeaux (sobre, pas de surlignage coloré).
- **Visage.** Les sous-titres se décalent automatiquement pour ne pas couvrir ton visage.
- **Zones Instagram.** Rien dans les 250 px du haut ni dans les 350 px du bas.
