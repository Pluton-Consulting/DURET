"""
Banc « RIEN NE SE SUPPRIME SANS LE MOT SUPPRIMÉ » (08/09).

Règle de Noa : « il ne doit jamais supprimer quoi que ce soit, à part si c'est
dit explicitement avec un mot "supprimé" dans le message envoyé ».

CE QUE CE BANC PROUVE (module EXÉCUTÉ, câblage lu dans la boucle d'actions) :
les gestes qui effacent sont reconnus par leur nom (liste ET préfixes,
fail-closed), le mot est cherché dans le MESSAGE de la personne sans accent ni
casse, le refus est rendu au modèle comme un résultat qui lui dit quoi dire,
et la boucle d'actions applique le garde AVANT de classer l'effet. Le prompt
porte la règle. Tombe sur la version d'avant.
"""
import pathlib, sys, types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ RIEN NE SE SUPPRIME SANS LE MOT « SUPPRIMÉ » — {BACKEND.parent}\n")
src = BACKEND / "skills" / "suppression.py"
verifier("le module `skills/suppression.py` existe", src.exists())
if not src.exists():
    sys.exit(1)
m = types.ModuleType("suppression_double")
exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), m.__dict__)
verifier("il ne déclare AUCUN skill (un module sans `SKILLS` : le registre l'ignore)", not hasattr(m, "SKILLS"))
verifier("les trois gestes qui effacent sont reconnus",
         all(m.est_une_suppression(s) for s in ("oublier", "supprimer_tache", "oublier_trame")))
verifier("un geste futur nommé supprimer_*/oublier_*/effacer_*/retirer_* l'est aussi (fail-closed)",
         all(m.est_une_suppression(s) for s in ("supprimer_dossier", "effacer_fichier", "retirer_acces", "oublier_client")))
verifier("lire, envoyer, abandonner un brouillon ne sont pas des suppressions",
         not any(m.est_une_suppression(s) for s in ("lire_mail", "envoyer_email", "abandonner_document", "nas_ouvrir", "")))
verifier("« supprime la tâche des mails » autorise", m.autorise_la_suppression("supprime la tâche des mails"))
verifier("« SUPPRIMÉ », « suppression », sans accent ni casse, autorisent",
         m.autorise_la_suppression("c'est SUPPRIMÉ ?") and m.autorise_la_suppression("suppression de la consigne")
         and m.autorise_la_suppression("Supprimer ça"))
verifier("« oublie ça », « enlève cette tâche », « efface », « laisse tomber » N'autorisent PAS",
         not any(m.autorise_la_suppression(t) for t in ("oublie ça", "enlève cette tâche", "efface la consigne", "on laisse tomber", "")))
r = m.raison_du_refus("supprimer_tache")
verifier("le refus nomme le geste, le mot attendu, et ce que le modèle doit dire",
         "supprimer_tache" in r and "« supprime »" in r and "Ne réessaie pas" in r and r.startswith("REFUSÉ"))

ag1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
i_garde, i_effet = ag1.find("from skills.suppression import"), ag1.find('effet_declare = effet_du_skill(action["skill"])')
verifier("la boucle d'actions applique le garde AVANT de classer l'effet du geste",
         0 < i_garde < i_effet)
zone = ag1[i_garde:i_effet]
verifier("…sur le MESSAGE de la personne (`state[\"query\"]`), jamais sur le texte du modèle",
         'autorise_la_suppression(state.get("query") or "")' in zone)
verifier("…et rend le refus comme un résultat (`ok: False`) sans exécuter, puis rend la main au modèle",
         '"ok": False' in zone and "raison_du_refus(action[\"skill\"])" in zone
         and 'return {"tool_results": resultats, "tool_iterations": iteration}' in zone)
verifier("le prompt porte la règle et ce qu'il faut répondre devant « oublie », « enlève »",
         "RIEN NE SE SUPPRIME SANS LE MOT « SUPPRIME »" in ag1 and "Ne supprime JAMAIS de ta propre initiative" in ag1)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs)); sys.exit(1)
print("✓ 0 échec")
