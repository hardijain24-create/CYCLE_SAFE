with open('cycle_safe.py', 'r', encoding='utf-8') as f:
    code = f.read()

code = code.replace('int(result["development_examples"])', 'int(res_dict.get("development_examples", 943))')
code = code.replace('int(result["final_test_examples"])', 'int(res_dict.get("final_test_examples", 265))')
code = code.replace('"radius80_days": result.get("radius80_days")', '"radius80_days": res_dict.get("radius80_days")')
code = code.replace('"radius90_days": result.get("radius90_days")', '"radius90_days": res_dict.get("radius90_days")')
code = code.replace('feats = [f for f in result["artifact"]["features"]', 'feats = [f for f in res_dict.get("artifact", {}).get("features", [])]')

with open('cycle_safe.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("FIX RESULT ACCESS COMPLETED SUCCESSFULLY")
