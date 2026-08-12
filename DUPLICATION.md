# Dupliquer ce projet pour un nouveau client

Le backend est découpé en un **socle** (identique d'un client à l'autre) et des
**modules de projet** (ce qui change). Adapter l'assistant à une nouvelle
entreprise ne touche pas le socle.

## Ce qu'on remplace

| Quoi | Où | Rôle |
|---|---|---|
| Les outils | `backend/outils/` | fonctions composées + leur doc (`docs/*.md`) |
| Les skills | `backend/skills/<projet>.py` | fonctions + **déclarations** (`SKILLS`) |
| L'identité | `backend/agents/agent1.py` (SYSTEM_PROMPT) | qui est l'entreprise, ses règles métier |
| La marque | `frontend/components/nav/Logo.tsx`, `app/layout.tsx` (jetons CSS), `app/icon.svg`, e-mail dans `routers/auth.py` | logo, charte, nom |
| Les secrets | `.env`, `backend/secrets/` | identifiants du client |

Tout le reste — graphe d'agents, exécuteur, validation humaine, anonymisation,
mémoire, imports, interface — est du socle : il se met à jour en tirant le
tronc commun, sans adaptation.

## Comment un skill existe

Un module de `backend/skills/` expose un dictionnaire `SKILLS` :

```python
from skills.registre import Declaration

SKILLS = {
    "mon_action": Declaration(
        fonction=mon_action,                  # async (data, user) -> dict
        description="CE QUE fait l'action, en une ligne, pour le modèle",
        requis=["parametre"], optionnels=["autre"],
        effet="lecture",                      # lecture | ecriture_interne | externe
        libelle="je fais l'action",           # affiché à l'écran pendant l'exécution
    ),
}
```

C'est **tout**. La découverte est automatique (`skills/registre.py`) : le
catalogue montré au modèle, l'exécuteur, la validation humaine et le journal
d'écran lisent cette déclaration. Il n'y a rien à enregistrer ailleurs.

### Les règles qui ne se contournent pas

- **`effet` est fail-closed** : non déclaré ou mal orthographié = `externe` =
  validation humaine obligatoire. Un oubli verrouille, il n'ouvre jamais.
- **Composer ne compose pas les droits** : une fonction qui enchaîne dix
  lectures déclare `lecture` ; une chaîne qui finit par une écriture hors du
  système déclare `externe`.
- **Un nom déjà pris est refusé** : un module de projet ne peut pas masquer un
  skill du socle, ni un autre module.

## Comment un outil existe

`backend/outils/<outil>.py` porte les fonctions composées (la logique, sans
notion d'utilisateur). `backend/outils/docs/<outil>.md` porte le mode d'emploi
complet — servi à la demande par l'action `mode_emploi`, jamais injecté dans le
prompt. Le registre des outils est le dictionnaire `OUTILS` de
`backend/outils/__init__.py`.

Règle d'or : **composer, pas multiplier**. Une fonction se justifie si elle
supprime des allers-retours sur une chaîne fréquente (mesuré ici : 57 % du temps
d'une demande part dans la conversation avec le modèle). Chaque description de
catalogue reste sous ~250 caractères ; le reste va dans la doc.

## La recette

1. Copier le dépôt, retirer `.git`, `git init`.
2. Vider `backend/skills/` de ce qui est propre à l'ancien client (ici :
   `nas.py`, `outils.py`) et `backend/outils/` en entier. Garder le socle :
   `registre.py`, `executor.py`, `protocol.py`, `erreurs.py`, `markdown.py`,
   `bureau.py`, `connaissances.py`, `documents.py`, `donnees.py`, `droits.py`.
3. Écrire les modules du nouveau client sur le modèle ci-dessus.
4. Réécrire le SYSTEM_PROMPT d'`agent1.py` (identité, métier, règles).
5. Remplacer la marque (voir tableau) et les secrets (`.env.example` commente
   chaque variable).
6. Lancer la batterie de vérifications avant le premier déploiement.

## Vérifier

`verif_registre.py` (scratchpad de développement) exécute la collecte sur le
vrai dossier `skills/` : déclarations complètes, effets sensibles, aucune trace
de l'autre projet. Les attentes suivent les fichiers présents — c'est la
définition même de la promesse.
