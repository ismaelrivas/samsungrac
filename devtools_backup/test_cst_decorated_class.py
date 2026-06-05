import libcst as cst

code = """
@register
class MyClass:
    def my_method(self):
        pass
"""

module = cst.parse_module(code)
class_def = module.body[0]
print("Top-level statement type:", type(class_def))
