with open('cycle_safe.py', 'r', encoding='utf-8') as f:
    code = f.read()

mock_block = '''if "result" not in globals():
    # Mock result for standalone running
    result = {
        "model_data": pd.DataFrame({"user_id": [1, 2, 3], "target": [28, 29, 30]}),
        "deployment_model_name": "ridge_v5",
        "artifact": {"version": "5.0"}
    }'''

code = code.replace(mock_block, '')

with open('cycle_safe.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("done")
