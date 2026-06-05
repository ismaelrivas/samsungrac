import os
import mutmut

def patch_mutmut():
    mutmut_dir = os.path.dirname(mutmut.__file__)
    print(f"Directorio de mutmut encontrado en: {mutmut_dir}")
    
    # Parche 1: Arreglar el error de "context has already been set" en __main__.py
    main_py_path = os.path.join(mutmut_dir, "__main__.py")
    if os.path.exists(main_py_path):
        with open(main_py_path, 'r') as f:
            main_code = f.read()
        
        target_main = "set_start_method('fork')"
        replacement_main = "try:\n    set_start_method('fork')\nexcept RuntimeError:\n    pass"
        
        if target_main in main_code and replacement_main not in main_code:
            main_code = main_code.replace(target_main, replacement_main)
            with open(main_py_path, 'w') as f:
                f.write(main_code)
            print("✅ Parche aplicado a __main__.py (multiprocessing fix)")
        else:
            print("ℹ️ El parche en __main__.py ya estaba aplicado o no se encontró.")

    # Parche 2: Evitar que se salten por completo las clases decoradas en file_mutation.py
    file_mut_path = os.path.join(mutmut_dir, "file_mutation.py")
    if os.path.exists(file_mut_path):
        with open(file_mut_path, 'r') as f:
            file_mut_code = f.read()
        
        target_file_mut = "isinstance(node, (cst.FunctionDef, cst.ClassDef))"
        replacement_file_mut = "isinstance(node, cst.FunctionDef)"
        
        if target_file_mut in file_mut_code:
            file_mut_code = file_mut_code.replace(target_file_mut, replacement_file_mut)
            with open(file_mut_path, 'w') as f:
                f.write(file_mut_code)
            print("✅ Parche aplicado a file_mutation.py (decorators fix)")
        else:
            print("ℹ️ El parche en file_mutation.py ya estaba aplicado o no se encontró.")

if __name__ == "__main__":
    patch_mutmut()
