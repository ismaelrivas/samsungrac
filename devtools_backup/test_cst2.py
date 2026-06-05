import libcst as cst

code = """
class MyClass:
    @staticmethod
    def my_method(self):
        pass
"""

module = cst.parse_module(code)
class_def = module.body[0]
for stmt in class_def.body.body:
    print("Method statement:", type(stmt))
