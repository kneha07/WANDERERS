# explain.json after the image-set refresh (#41)

Resolved: the five texts were regenerated with `pipeline/explain.py` from the new cards (commit "Regenerate the five
explain.json texts…", #45). No old number remains. `explain.py` now reads the Claude CLI output as UTF-8; before, on
Windows it saved `″` and `±` as broken characters.

The old texts quoted, for example: Barnard 10.40″/yr (now 10.39), WISE 0855 methane 5.1× (now "> 4×", a lower limit),
R Draconis drift 0.43″/yr (now 0.09). Verdicts did not change.
