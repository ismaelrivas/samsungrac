
with open('fast_mutmut_show.py', 'r') as f:
    lines = f.read()

# I will just run pytest using mutmut to see if any mutant survived in async_execute.
# Actually, the user has patch_mutmut_v3.py which modifies the source code to add `# pragma: no mutate` or uses AST to mutate.
# The user's system runs `mutmut` directly! Let's check `mutmut run`.
