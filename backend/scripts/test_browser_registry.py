"""Exécuter le vrai goulot des actions, avec une bibliothèque navigateur doublée."""
import sys,types,ast,asyncio,json
from pathlib import Path
B=Path(sys.argv[1]).resolve();root=B.parent
s=(root/'browser-worker/browser_agent.py').read_text();tree=ast.parse(s);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_tools')
class ActionResult:
 def __init__(self,**kw):self.__dict__.update(kw)
class Tools:
 def __init__(self,**kw):
  self.executions=[]
  async def execute_action(name,params,**kw):self.executions.append((name,params));return 'fait'
  self.registry=types.SimpleNamespace(execute_action=execute_action,registry=types.SimpleNamespace(actions={n:None for n in ['navigate','click','input','read_file','evaluate','done']}))
 def exclude_action(self,n):self.registry.registry.actions.pop(n,None)
m=types.ModuleType('browser_use');m.Tools=Tools;m.ActionResult=ActionResult;sys.modules['browser_use']=m
class DB:
 def __init__(self):self.validations=[]
 async def insert_validation(self,**kw):self.validations.append(kw);return 'v'
 async def update_status(self,*a):pass
 async def log_audit(self,*a,**kw):pass
 async def purge_validation_screenshot(self,*a):pass
async def capture(session):return None
decision='rejected'
async def attendre(vid):return decision
async def url():return 'https://example.test/formulaire'
db=DB();ns={'json':json,'db':db,'_capture_screenshot':capture,'_wait_for_decision':attendre};exec(compile(ast.Module(body=[node],type_ignores=[]),'browser','exec'),ns)
async def test():
 global decision
 t=ns['build_tools']('job','user',True)
 assert 'click' not in t.registry.registry.actions
 assert await t.registry.execute_action('navigate',{'url':'https://example.test'})=='fait'
 # Même un outil réintroduit après la construction est refusé à l'exécution.
 for n in ('click','evaluate','read_file','nouvel_outil'):
  try:await t.registry.execute_action(n,{});raise AssertionError('Action interdite passée')
  except RuntimeError:pass
 assert len(t.executions)==1
 t=ns['build_tools']('job','user',False);session=types.SimpleNamespace(get_current_page_url=url)
 try:await t.registry.execute_action('click',{'index':5},browser_session=session);raise AssertionError('Refus humain contourné')
 except RuntimeError:pass
 assert not t.executions and len(db.validations)==1
 decision='approved';await t.registry.execute_action('click',{'index':5},browser_session=session)
 assert t.executions==[('click',{'index':5})] and len(db.validations)==2
asyncio.run(test());print('✓ Mode lecture bloqué au goulot réel, actions dynamiques refusées, écriture exécutée seulement après accord exact')
