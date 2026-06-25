import os
os.system("cp mutmut_results_7.txt survived5.log")
os.system("python3 custom_components/climate_ip/scripts/dump_all_fast_optimized.py survived5.log > mutantes.txt")
os.system("python3 custom_components/climate_ip/scripts/group_and_deduplicate.py mutantes.txt > mutant_analysis_7.md")
