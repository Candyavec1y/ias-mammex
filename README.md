# SE-Sein — système expert d'aide au diagnostic du cancer du sein

Mouradian · Pasquier · Mollier — implémentation fidèle à la présentation finale
(11 règles sur 2 niveaux, facteurs de certitude, moteur mixte, méta-règles MR1-MR5, heuristiques H1-H5).

> Aide à la décision : SE-Sein ne remplace pas l'avis du médecin, et seule la biopsie confirme un cancer.
> Les CF sont des valeurs pédagogiques, à faire valider par un expert.

---

## 1. Lancer SE-Sein sur Mac

Rien à installer à part Python 3, déjà présent sur la plupart des Mac.

**Méthode simple**

1. Décompressez le dossier `se-sein` (par exemple dans Documents).
2. Double-cliquez sur **`Lancer SE-Sein.command`**.
   - Au premier lancement, macOS peut bloquer le fichier (« développeur non identifié »).
     Faites alors **clic droit → Ouvrir → Ouvrir**. Il suffit de le faire une seule fois.
   - Si macOS propose d'installer les « outils de ligne de commande », acceptez : cela installe Python.
3. Le navigateur s'ouvre sur **http://127.0.0.1:8765/**. Laissez la fenêtre noire (Terminal) ouverte
   pendant l'utilisation, et fermez-la pour arrêter SE-Sein.

**Méthode Terminal**

```bash
cd ~/Documents/se-sein        # le dossier décompressé
python3 lancer.py
```

Options : `python3 lancer.py --port 9000` ou `python3 lancer.py --sans-navigateur`.

Le serveur n'écoute que sur votre ordinateur (127.0.0.1) : aucune donnée ne sort de la machine,
et rien n'est conservé entre deux consultations.

## 2. Interface médecin — http://127.0.0.1:8765/

- **Saisie guidée** en 4 étapes (Terrain → Clinique → Imagerie → Biopsie), une question à la fois,
  avec une barre de progression. L'étape Biopsie n'est posée que si elle peut changer la décision (H4).
- **Réponses** : Oui / Non / Je ne sais pas. Après un Oui, le médecin choisit Certain (1,0), Probable (0,7)
  ou Possible (0,4). L'âge est affiché en valeur floue (« âgée à 80 % »).
- **Raccourcis clavier** : O / N / J, puis 1 / 2 / 3 pour la certitude ; ← pour la question précédente.
- **Pourquoi ?** pendant les questions, par exemple : « Je vous demande si une biopsie a été faite car je cherche à
  prouver « Cancer confirmé » (R7) ».
- **Résultat** : hypothèse en gros, couleur selon la gravité (rouge, orange, vert, gris), jauge de CF en teinte
  neutre avec sa lecture en texte, recommandations numérotées, alertes, données manquantes et hypothèses secondaires.
- **Comment ?** : redescend la trace du niveau 2 au niveau 1, avec le détail de chaque calcul de CF.
- **Rapport imprimable** (ou « Enregistrer en PDF » depuis la fenêtre d'impression), prêt à joindre au dossier.
- **Cas de démonstration** : les 5 cas de la présentation et leurs variantes, en un clic.

## 3. Interface expert — http://127.0.0.1:8765/expert

Code d'accès par défaut : **`expert-sein`**. Il est modifiable dans `data/config.json`, créé au premier lancement.

- **Règles** : modifier la prémisse, la conclusion, le CF et la recommandation ; activer, désactiver, ajouter ou supprimer
  une règle. La prémisse est vérifiée en direct (faute de frappe, fait inconnu, niveau incohérent).
  Syntaxe : `ET`, `OU`, `NON`, `age EST agee`, `biopsie_resultat = carcinome`, parenthèses.
- **Faits et questions** : questions posées au médecin, faits intermédiaires, diagnostics (et leur couleur), variable floue.
- **Méta-règles et heuristiques** : seuils, ordre de test H1, conditions de MR4 et de H4, recommandation de MR5…
- **Paramètres** : seuil d'activation (0,2), CF de Certain / Probable / Possible, paliers de lecture du CF.
- **Vérification automatique** : syntaxe, contradictions, redondances, trous de couverture,
  règles jamais déclenchées et non-régression sur les 8 cas de référence. On peut aussi essayer un cas avec la base en cours d'édition.
- **Versions** : chaque enregistrement crée une version (auteur, date, motif), et la base n'est enregistrée
  que si la vérification ne trouve aucune erreur. On peut comparer une version à la version active et la restaurer ;
  rien n'est jamais effacé.

## 4. Tests

```bash
python3 -m unittest discover -s tests -v
```

Les 5 cas de la présentation et leurs variantes (cas 4 avec biopsie bénigne, cas 4 sans clinique, cas 5 avec clinique
inconnue) redonnent exactement les conclusions et les CF des slides 11-12 :

| Cas | Conclusion | CF | Couleur |
|---|---|---|---|
| 1 · 58 ans, nodule dur fixé, image spiculée | Cancer très probable | 0,72 | rouge |
| 2 · 62 ans, peau d'orange, biopsie positive | Cancer confirmé | 1,00 | rouge |
| 3 · 28 ans, nodule mobile, image ovale | Probablement bénin | 0,77 | vert |
| 4 · 52 ans, clinique douteuse, image ovale | Lésion suspecte | 0,46 | orange |
| 5 · 40 ans, BRCA, sans symptôme | Indéterminé | — | gris |

## 5. Organisation du code

```
lancer.py                     démarre le serveur et ouvre le navigateur
Lancer SE-Sein.command        lanceur double-cliquable (Mac)
se_sein/dsl.py                langage des prémisses, calculs ET / OU / NON / flou
se_sein/moteur.py             moteur d'inférence (chaînage avant puis arrière, MR, H, trace, explications)
se_sein/verification.py       vérification automatique de la base
se_sein/base.py               lecture, écriture et versions de la base
se_sein/serveur.py            serveur web local (bibliothèque standard Python uniquement)
data/base_connaissances.json  LA base de connaissances (règles, méta-règles, heuristiques, questions)
data/cas_reference.json       cas de référence (tests et démonstration)
data/versions/                historique des versions (créé au premier lancement)
web/                          interfaces médecin et expert (HTML / CSS / JavaScript, sans dépendance)
tests/test_cas.py             tests
```

## 6. Choix d'implémentation

Ces points précisent ce que la présentation laisse implicite. Ils sont à connaître pour les questions du jury.

1. **Fait absent dans un ET** : si un terme connu vaut 0, le ET vaut 0 (le résultat ne peut pas être plus grand) ;
   sinon, il manque une donnée et la règle ne se déclenche pas. Un OU se calcule sur les faits connus (slide 6).
2. **Fait intermédiaire incomplet** : si une des règles qui le concluent n'est pas évaluable, le fait est « incomplet ».
   On peut s'en servir positivement (R8, R9), mais pas sous un **NON** : on ne peut pas affirmer une absence.
   C'est ce qui bloque R10 quand le terrain ou la clinique manquent.
3. **Questions sans objet** : « nodule fixé » n'est pas posée si le nodule n'est pas dur, et « aucune anomalie »
   n'est pas posée si une masse est déjà décrite. Elles valent alors Non.
4. **H4** : la biopsie est demandée si l'imagerie suspecte est établie (CF ≥ 0,2) ou si la suspicion clinique est ≥ 0,4.
   Un résultat déjà connu est toujours utilisé.
5. **MR2** : R7 et R11 sont toutes deux évaluées (comme dans le cas 2), puis R8 à R10 sont écartées si l'une atteint 0,9.
6. **MR3** : une donnée de terrain ou de clinique répondue « Je ne sais pas » est redemandée une fois avant d'ouvrir le
   niveau 2 (le nombre de demandes est réglable).
7. **R9 après une biopsie bénigne** (variante du cas 4) : la recommandation devient « nouvelle biopsie ou RCP ».
8. **H3** : en cas de discordance radio-clinique, une alerte est affichée. L'effet « la plus grave l'emporte »
   résulte de l'ordre H1 et de MR4.
9. Le module « Pourquoi ? » des questions de recueil cite les règles qui utilisent la donnée.

**Deux écarts relevés dans la présentation**

- Slide 4 : « avant **40** ans → μ = 0 » ; la formule et les notes disent **50**, et c'est 50 qui est implémenté.
- Cas 4 : R10 sans MR4 vaut **0,29** en calcul exact (0,85 × 0,3468). La slide donne 0,30 car elle arrondit 0,35 avant
  de multiplier ; la conclusion ne change pas.
