import math

# Calibrated magnetising curve (piecewise linear, matches Siemens doc examples)
_IMAG_CURVE = [
    (0.0, 0.000), (0.1, 0.040), (0.2, 0.100), (0.3, 0.170),
    (0.4, 0.250), (0.5, 0.380), (0.6, 0.520), (0.7, 0.660),
    (0.8, 0.800), (0.9, 0.910), (1.0, 1.000)
]

def interpolate_imag(Vs, Vk, Imag_at_Vk_mA):
    """Return Imag in Amps at Vs using calibrated magnetising curve."""
    if Vk <= 0 or Imag_at_Vk_mA <= 0:
        return 0.0
    ratio = min(max(Vs / Vk, 0.0), 1.0)
    for i in range(len(_IMAG_CURVE) - 1):
        r0, f0 = _IMAG_CURVE[i]
        r1, f1 = _IMAG_CURVE[i + 1]
        if r0 <= ratio <= r1:
            t = (ratio - r0) / (r1 - r0)
            factor = f0 + t * (f1 - f0)
            return (Imag_at_Vk_mA / 1000.0) * factor
    return Imag_at_Vk_mA / 1000.0

def calculate_hiref(inp):
    config      = inp["config"]
    MVA         = inp["mva"]
    VkV         = inp["voltage_kv"]
    IF_mult     = inp["if_multiplier"]
    POC_pct     = inp["poc_pct"]
    relay_Is    = inp["relay_is"]

    # LCT
    T_lct       = inp["T_lct"]
    Vk_lct      = inp["Vk_lct"]
    Imag_Vk_lct = inp["Imag_Vk_lct"]      # mA
    RCT_lct     = inp["RCT_lct"]
    RL_lct      = inp["RL_lct"]
    imag_m_lct  = inp.get("imag_method_lct", "interpolate")
    Imag_Vs_lct_in = inp.get("Imag_Vs_lct", 0.0)

    T_nct       = inp.get("T_nct", T_lct)
    Vk_nct      = inp.get("Vk_nct", 450.0)
    Imag_Vk_nct = inp.get("Imag_Vk_nct", 20.0)
    RCT_nct     = inp.get("RCT_nct", 4.5)
    RL_nct      = inp.get("RL_nct", 0.5)
    imag_m_nct  = inp.get("imag_method_nct", "interpolate")
    Imag_Vs_nct_in = inp.get("Imag_Vs_nct", 0.0)

    T_ect       = inp.get("T_ect", T_lct)
    Vk_ect      = inp.get("Vk_ect", 300.0)
    Imag_Vk_ect = inp.get("Imag_Vk_ect", 40.0)
    RCT_ect     = inp.get("RCT_ect", 6.0)
    RL_ect      = inp.get("RL_ect", 0.2)
    imag_m_ect  = inp.get("imag_method_ect", "interpolate")
    Imag_Vs_ect_in = inp.get("Imag_Vs_ect", 0.0)

    # ── STEP 1: SYSTEM ────────────────────────────────────────────
    I_rated = (MVA * 1e6) / (math.sqrt(3) * VkV * 1000)
    IF      = IF_mult * I_rated
    POC_min = 0.10 * I_rated
    POC_max = 0.25 * I_rated
    POC     = (POC_pct / 100.0) * I_rated

    # ── STEP 2: STABILITY VOLTAGE ─────────────────────────────────
    Vs_lct_req = (IF / T_lct) * (RCT_lct + RL_lct)
    Vs_nct_req = 0.0
    Vs_ect_req = 0.0

    Vk_list = [Vk_lct]
    Vs_list = [Vs_lct_req]

    if config in [3, 4]:
        Vs_nct_req = (IF / T_nct) * (RCT_nct + RL_nct)
        Vs_list.append(Vs_nct_req)
        Vk_list.append(Vk_nct)
    if config in [2, 4]:
        Vs_ect_req = (IF / T_ect) * (RCT_ect + RL_ect)
        Vs_list.append(Vs_ect_req)
        Vk_list.append(Vk_ect)

    Vs_min   = max(Vs_list)
    Vk_min   = min(Vk_list)
    Vs_max   = Vk_min / 2.0

    # Provisional Vs: round up to next 10V, capped at Vs_max
    Vs_prov = math.ceil((Vs_min + 1) / 10.0) * 10.0
    Vs_prov = min(Vs_prov, Vs_max)
    Vs_ok   = (Vs_min < Vs_prov <= Vs_max)

    # ── STEP 3: IMAG @ Vs_prov ───────────────────────────────────
    def get_imag(method, Vs, Vk, Imag_Vk_mA, entered_mA):
        if method == "interpolate":
            return interpolate_imag(Vs, Vk, Imag_Vk_mA)
        else:
            return (entered_mA or 0.0) / 1000.0

    Imag_lct = get_imag(imag_m_lct, Vs_prov, Vk_lct, Imag_Vk_lct, Imag_Vs_lct_in)
    Imag_nct = get_imag(imag_m_nct, Vs_prov, Vk_nct, Imag_Vk_nct, Imag_Vs_nct_in) if config in [3,4] else 0.0
    Imag_ect = get_imag(imag_m_ect, Vs_prov, Vk_ect, Imag_Vk_ect, Imag_Vs_ect_in) if config in [2,4] else 0.0

    # ── STEP 4: RELAY SETTING & RSTAB ────────────────────────────
    if config == 1:
        sum_Imag = 3 * Imag_lct
        poc_formula = "(3×Imag_LCT + Is) / T"
    elif config == 2:
        sum_Imag = 3 * Imag_lct + Imag_ect
        poc_formula = "(3×Imag_LCT + Imag_ECT + Is) / T"
    elif config == 3:
        sum_Imag = 3 * Imag_lct + Imag_nct
        poc_formula = "(3×Imag_LCT + Imag_NCT + Is) / T"
    else:
        sum_Imag = 3 * Imag_lct + Imag_nct + Imag_ect
        poc_formula = "(3×Imag_LCT + Imag_NCT + Imag_ECT + Is) / T"

    POC_sec   = POC / T_lct
    Is_ideal  = POC_sec - sum_Imag
    Is        = max(relay_Is if relay_Is > 0 else Is_ideal, 0.005)

    Rstab_raw = Vs_prov / Is
    # Round to nearest 50Ω standard
    Rstab_std = max(int(math.ceil(Rstab_raw / 50)) * 50, 50)
    Vs_actual = Rstab_std * Is

    # Re-check Vs_actual within limits
    Vs_final_ok = (Vs_min < Vs_actual <= Vs_max)
    POC_actual  = (sum_Imag + Is) * T_lct

    # ── STEP 5: METROSIL ─────────────────────────────────────────
    IFint_sec   = IF / T_lct
    P1SEC_metro = (4.0 / math.pi) * IF * (1.0 / T_lct) * Vk_min

    if P1SEC_metro < 8000:
        metro_size, metro_rating = "75 mm", "8 kJ"
    else:
        metro_size, metro_rating = "150 mm", "33 kJ"

    C_val = 450 if Vs_actual < 100 else 1000

    # Peak voltage without Metrosil
    try:
        arg = 2 * Vk_min * (IFint_sec * Rstab_std - Vk_min)
        VPk = math.sqrt(2) * math.sqrt(max(arg, 0)) if arg > 0 else 0
    except:
        VPk = 0

    # ── STEP 6: RESISTOR RATINGS ──────────────────────────────────
    P_cont   = Is**2 * Rstab_std
    IFint    = IF / T_lct
    try:
        VFint = (Vk_min * Rstab_std * IFint)**0.75 * 1.3
    except:
        VFint = 0.0
    P1SEC_res = VFint**2 / Rstab_std if Rstab_std > 0 else 0.0

    Vk_required = 2.0 * Vs_actual
    Vk_check    = Vk_lct >= Vk_required

    return {
        "I_rated": I_rated, "IF": IF, "POC_min": POC_min,
        "POC_max": POC_max, "POC": POC, "IF_mult": IF_mult,
        "Vs_lct_req": Vs_lct_req, "Vs_nct_req": Vs_nct_req,
        "Vs_ect_req": Vs_ect_req, "Vs_min": Vs_min,
        "Vs_max": Vs_max, "Vs_prov": Vs_prov, "Vk_min": Vk_min,
        "Vs_ok": Vs_ok,
        "Imag_lct": Imag_lct, "Imag_nct": Imag_nct, "Imag_ect": Imag_ect,
        "sum_Imag": sum_Imag,
        "Is": Is, "Is_ideal": Is_ideal, "POC_sec": POC_sec,
        "Rstab_raw": Rstab_raw, "Rstab_std": Rstab_std,
        "Vs_actual": Vs_actual, "Vs_final_ok": Vs_final_ok,
        "POC_actual": POC_actual, "poc_formula": poc_formula,
        "P1SEC_metro": P1SEC_metro, "metro_size": metro_size,
        "metro_rating": metro_rating, "C_val": C_val,
        "IFint_sec": IFint_sec, "VPk": VPk,
        "P_cont": P_cont, "VFint": VFint, "P1SEC_res": P1SEC_res,
        "Vk_check": Vk_check, "Vk_required": Vk_required,
        "config": config, "T_lct": T_lct, "MVA": MVA, "VkV": VkV,
    }
