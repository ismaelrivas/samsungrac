for i in {1..587}; do
    out=$(mutmut show $i 2>/dev/null)
    if echo "$out" | grep -q 'survived'; then
        echo "=== Mutant $i ===" >> real_survivors.txt
        echo "$out" >> real_survivors.txt
        echo "" >> real_survivors.txt
    fi
done
