import libcst as cst

code = """
class MyClass:
    def my_method(self):
        pass
"""

module = cst.parse_module(code)
class_def = module.body[0]
print(type(class_def.body))
for stmt in class_def.body.body:
    print("Method statement:", type(stmt))
