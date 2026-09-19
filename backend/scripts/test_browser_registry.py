"""Exécuter le vrai goulot des actions, avec une bibliothèque navigateur doublée.

19/09 : la lecture ne retire plus tout clic — elle laisse suivre un lien, ouvrir un menu,
fermer une bannière (jugé par `lecture_sure` sur l'élément visé) et refuse ce qui ENVOIE.
Ce banc exécute `build_tools` tel qu'il est livré et vérifie, au goulot réel :
  * lecture : un lien s'ouvre ; un bouton de formulaire posté est refusé (erreur rendue à
    l'agent, rien d'exécuté) ; un outil hors liste, même réintroduit après coup, est refusé ;
  * écriture : un lien s'ouvre sans accord ; un envoi attend l'accord humain exact ;
  * l'action `search` est celle du conteneur, pas celle qui ouvre Google dans l'onglet.
"""
import sys, types, ast, asyncio, json, importlib.util
from pathlib import Path

B = Path(sys.argv[1]).resolve()
root = B.parent
s = (root / 'browser-worker/browser_agent.py').read_text()
tree = ast.parse(s)
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_tools')


class ActionResult:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Tools:
    def __init__(self, **kw):
        self.executions = []

        async def execute_action(name, params, **kw):
            self.executions.append((name, params))
            return 'fait'

        def action(description, param_model=None, **kw):
            def deco(f):
                self.registry.registry.actions[f.__name__] = f
                return f
            return deco

        self.registry = types.SimpleNamespace(
            execute_action=execute_action, action=action,
            registry=types.SimpleNamespace(actions={n: None for n in
                                                    ['navigate', 'click', 'input', 'read_file', 'evaluate', 'done', 'search']}))

    def exclude_action(self, n):
        self.registry.registry.actions.pop(n, None)


m = types.ModuleType('browser_use')
m.Tools = Tools
m.ActionResult = ActionResult
sys.modules['browser_use'] = m

spec = importlib.util.spec_from_file_location("lecture_sure", root / "browser-worker" / "lecture_sure.py")
lecture_sure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lecture_sure)


class DB:
    def __init__(self):
        self.validations = []

    async def insert_validation(self, **kw):
        self.validations.append(kw)
        return 'v'

    async def update_status(self, *a):
        pass

    async def log_audit(self, *a, **kw):
        pass

    async def purge_validation_screenshot(self, *a):
        pass


async def capture(session):
    return None

decision = 'rejected'


async def attendre(vid):
    return decision


class Noeud:
    def __init__(self, tag, attrs=None, texte="", parent=None):
        self.tag_name, self.attributes, self._t, self.parent_node = tag, attrs or {}, texte, parent

    def get_all_children_text(self):
        return self._t


page = Noeud("body")
form_post = Noeud("form", {"method": "post"}, parent=page)
ELEMENTS = {5: Noeud("button", {"type": "submit"}, "Envoyer", form_post),
            7: Noeud("a", {"href": "/fr/produits/taralay"}, "Taralay", page)}


class Session:
    async def get_current_page_url(self):
        return 'https://example.test/formulaire'

    async def get_element_by_index(self, i):
        return ELEMENTS.get(i)


db = DB()
ns = {'json': json, 'db': db, '_capture_screenshot': capture, '_wait_for_decision': attendre,
      'lecture_sure': lecture_sure, '_rechercher': None}
exec(compile(ast.Module(body=[node], type_ignores=[]), 'browser', 'exec'), ns)
session = Session()


async def test():
    global decision
    # ── LECTURE ──
    t = ns['build_tools']('job', 'user', True, ['example.test', '*.example.test'])
    acts = t.registry.registry.actions
    assert 'click' in acts and 'input' in acts, "la lecture doit garder les interactions jugées"
    assert 'evaluate' not in acts and 'read_file' not in acts, "un outil hors liste reste retiré"
    assert callable(acts.get('search')), "l'action search doit être celle du conteneur"
    assert await t.registry.execute_action('navigate', {'url': 'https://example.test'}) == 'fait'
    assert await t.registry.execute_action('click', {'index': 7}, browser_session=session) == 'fait', \
        "un lien doit s'ouvrir en lecture"
    r = await t.registry.execute_action('click', {'index': 5}, browser_session=session)
    assert isinstance(r, ActionResult) and 'formulaire' in r.error, "un envoi doit être refusé en lecture"
    r = await t.registry.execute_action('click', {'coordinate_x': 3, 'coordinate_y': 4}, browser_session=session)
    assert isinstance(r, ActionResult) and r.error, "un clic sans élément doit être refusé"
    # Même un outil réintroduit après la construction est refusé à l'exécution.
    for n in ('evaluate', 'read_file', 'nouvel_outil'):
        try:
            await t.registry.execute_action(n, {})
            raise AssertionError('Action interdite passée')
        except RuntimeError:
            pass
    assert t.executions == [('navigate', {'url': 'https://example.test'}), ('click', {'index': 7})], t.executions
    assert not db.validations, "la lecture ne demande jamais d'accord"

    # ── ÉCRITURE ──
    t = ns['build_tools']('job', 'user', False, ['example.test'])
    assert await t.registry.execute_action('click', {'index': 7}, browser_session=session) == 'fait'
    assert not db.validations, "un lien s'ouvre sans accord, même en écriture"
    try:
        await t.registry.execute_action('click', {'index': 5}, browser_session=session)
        raise AssertionError('Refus humain contourné')
    except RuntimeError:
        pass
    assert t.executions == [('click', {'index': 7})] and len(db.validations) == 1
    decision = 'approved'
    await t.registry.execute_action('click', {'index': 5}, browser_session=session)
    assert t.executions == [('click', {'index': 7}), ('click', {'index': 5})] and len(db.validations) == 2

asyncio.run(test())
print('✓ Lecture : liens ouverts, envois refusés au goulot réel, outils hors liste refusés ; '
      'écriture : envoi exécuté seulement après accord exact')
