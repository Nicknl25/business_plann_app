# mini's own R31 dump: HOME gate code, app code bound per --root, canonical json digest.
import sys, json, hashlib
root, out = sys.argv[1], sys.argv[2]
HOME = r"C:\dev\business_plann_app"
sys.path.insert(0, HOME)
from replay_gate import _bootstrap
_bootstrap.utf8_stdout()
_bootstrap.bind_root(root)
from replay_gate.context import GateContext
ctx = GateContext(_bootstrap.gate_connection(), _bootstrap.read_connection())
ctx.assert_surface()
draft, mij, finmo, note = ctx.single_line_payloads()
canon = lambda p: json.dumps(p, sort_keys=True, separators=(",", ":"), default=str)
import api_handlers.intake_consult as ic
mi = hashlib.sha256(canon(mij).encode()).hexdigest()[:12]
fm = hashlib.sha256(canon(finmo).encode()).hexdigest()[:12]
json.dump({"build": _bootstrap.build_id(), "ic": ic.__file__, "model_input": mij, "finmo": finmo}, open(out, "w", encoding="utf-8"), sort_keys=True, default=str)
print("MINI", _bootstrap.build_id(), "ic=", ic.__file__, "model_input", mi, "finmo", fm)
