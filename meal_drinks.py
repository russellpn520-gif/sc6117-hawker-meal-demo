"""Reference recipe and ingredient IDs used in previously saved counter drinks."""

# Estimated 200 g cup. Nutrition is calculated from these local USDA entries.
KOPI_C_PORTIONS = {"fdc-2710375": 175, "fdc-2705399": 20, "fdc-169655": 5}
LEGACY_CUP_FOODS = {"kopi": ("fdc-2710375",), "kopi_c": tuple(KOPI_C_PORTIONS),
                    "teh": ("fdc-173227",), "soy": ("fdc-2705405",)}
