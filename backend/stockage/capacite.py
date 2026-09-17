"""Réserve disque avant une nouvelle production ; ne purge aucune donnée."""
import os,shutil

def etat(dossier):
    os.makedirs(dossier,exist_ok=True)
    usage=shutil.disk_usage(dossier)
    try:reserve=max(0,int(os.environ.get("DOCUMENTS_RESERVE_MO","128")))*1024*1024
    except ValueError:raise ValueError("DOCUMENTS_RESERVE_MO doit être un entier positif.")
    return {"libre_octets":usage.free,"reserve_octets":reserve,"alerte":usage.free<max(reserve*4,512*1024*1024)}

def verifier(dossier,octets=0):
    e=etat(dossier)
    if e["libre_octets"] < e["reserve_octets"] + max(0,int(octets))*2:
        raise ValueError("Espace disque insuffisant pour produire ce document sans risquer les données existantes. Libérez de l’espace ou augmentez le volume ; aucun ancien document supprimé.")
    return e
