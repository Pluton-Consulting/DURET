"""
Connecteurs sources externes. Chacun expose `async def sync() -> dict`.
Import paresseux des dépendances lourdes (google, msal, pandas…) : le module s'importe
toujours, mais `sync()` lève NotImplementedError tant que les identifiants manquent.
"""
