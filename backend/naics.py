"""
NAICS validation layer — post-processing rule check.

The LLM proposes a NAICS code and industry. We do NOT trust it blindly:
we validate the code against a known lookup table, check whether the code's
official description is consistent with the predicted industry, and surface a
rule-based "expected risk" so a human can see where the model agrees/disagrees.
"""

# Common commercial NAICS codes relevant to small-business underwriting.
# base_risk = rough inherent hazard tier for that class of business.
NAICS_TABLE = {
    "722511": {"description": "Full-Service Restaurants", "keywords": ["restaurant", "dining", "food", "eatery"], "base_risk": "MEDIUM"},
    "722513": {"description": "Limited-Service Restaurants", "keywords": ["fast food", "restaurant", "food", "quick service", "takeout"], "base_risk": "MEDIUM"},
    "722410": {"description": "Drinking Places (Alcoholic Beverages)", "keywords": ["bar", "pub", "tavern", "nightclub", "lounge"], "base_risk": "HIGH"},
    "311811": {"description": "Retail Bakeries", "keywords": ["bakery", "baked", "pastry"], "base_risk": "LOW"},
    "445110": {"description": "Supermarkets and Grocery Stores", "keywords": ["grocery", "supermarket", "market"], "base_risk": "LOW"},
    "447110": {"description": "Gasoline Stations with Convenience Stores", "keywords": ["gas station", "fuel", "petrol", "convenience"], "base_risk": "HIGH"},
    "448140": {"description": "Family Clothing Stores", "keywords": ["clothing", "apparel", "retail", "fashion"], "base_risk": "LOW"},
    "451110": {"description": "Sporting Goods Stores", "keywords": ["sporting", "sports", "outdoor", "retail"], "base_risk": "LOW"},
    "454110": {"description": "Electronic Shopping and Mail-Order Houses", "keywords": ["ecommerce", "online", "retail", "mail order"], "base_risk": "LOW"},
    "441110": {"description": "New Car Dealers", "keywords": ["car dealer", "auto dealer", "dealership", "automotive sales"], "base_risk": "MEDIUM"},
    "811111": {"description": "General Automotive Repair", "keywords": ["auto repair", "automotive", "mechanic", "garage", "car repair"], "base_risk": "MEDIUM"},
    "811121": {"description": "Automotive Body, Paint, and Interior Repair", "keywords": ["body shop", "auto body", "paint", "collision"], "base_risk": "HIGH"},
    "811192": {"description": "Car Washes", "keywords": ["car wash", "auto detail", "detailing"], "base_risk": "MEDIUM"},
    "236220": {"description": "Commercial and Institutional Building Construction", "keywords": ["construction", "general contractor", "building"], "base_risk": "HIGH"},
    "238210": {"description": "Electrical Contractors", "keywords": ["electrical", "electrician", "wiring"], "base_risk": "HIGH"},
    "238160": {"description": "Roofing Contractors", "keywords": ["roofing", "roofer", "roof"], "base_risk": "HIGH"},
    "238110": {"description": "Poured Concrete Foundation and Structure Contractors", "keywords": ["concrete", "foundation", "masonry"], "base_risk": "HIGH"},
    "238220": {"description": "Plumbing, Heating, and Air-Conditioning Contractors", "keywords": ["plumbing", "hvac", "heating", "plumber"], "base_risk": "MEDIUM"},
    "484110": {"description": "General Freight Trucking, Local", "keywords": ["trucking", "freight", "hauling", "delivery", "logistics"], "base_risk": "HIGH"},
    "484121": {"description": "General Freight Trucking, Long-Distance", "keywords": ["trucking", "freight", "long haul", "logistics", "transport"], "base_risk": "HIGH"},
    "493110": {"description": "General Warehousing and Storage", "keywords": ["warehouse", "storage", "distribution"], "base_risk": "MEDIUM"},
    "561730": {"description": "Landscaping Services", "keywords": ["landscaping", "lawn", "garden", "groundskeeping"], "base_risk": "MEDIUM"},
    "562111": {"description": "Solid Waste Collection", "keywords": ["waste", "garbage", "trash", "refuse", "recycling"], "base_risk": "HIGH"},
    "332710": {"description": "Machine Shops", "keywords": ["machine shop", "machining", "fabrication", "cnc"], "base_risk": "HIGH"},
    "332999": {"description": "All Other Miscellaneous Fabricated Metal Product Manufacturing", "keywords": ["metal", "fabrication", "manufacturing"], "base_risk": "HIGH"},
    "321113": {"description": "Sawmills", "keywords": ["sawmill", "lumber", "timber", "wood"], "base_risk": "HIGH"},
    "423510": {"description": "Metal Service Centers and Other Metal Merchant Wholesalers", "keywords": ["metal wholesale", "steel", "distribution"], "base_risk": "MEDIUM"},
    "541110": {"description": "Offices of Lawyers", "keywords": ["law", "legal", "attorney", "lawyer"], "base_risk": "LOW"},
    "541211": {"description": "Offices of Certified Public Accountants", "keywords": ["accounting", "cpa", "accountant", "tax", "bookkeeping"], "base_risk": "LOW"},
    "541330": {"description": "Engineering Services", "keywords": ["engineering", "engineer", "design"], "base_risk": "MEDIUM"},
    "541512": {"description": "Computer Systems Design Services", "keywords": ["software", "it", "technology", "computer", "saas", "consulting"], "base_risk": "LOW"},
    "524210": {"description": "Insurance Agencies and Brokerages", "keywords": ["insurance", "broker", "agency"], "base_risk": "LOW"},
    "522110": {"description": "Commercial Banking", "keywords": ["bank", "banking", "financial"], "base_risk": "LOW"},
    "621111": {"description": "Offices of Physicians (except Mental Health)", "keywords": ["physician", "doctor", "medical", "clinic", "healthcare"], "base_risk": "MEDIUM"},
    "621210": {"description": "Offices of Dentists", "keywords": ["dentist", "dental", "orthodontic"], "base_risk": "LOW"},
    "623110": {"description": "Nursing Care Facilities (Skilled Nursing)", "keywords": ["nursing", "skilled care", "elder care", "assisted living"], "base_risk": "HIGH"},
    "624410": {"description": "Child Day Care Services", "keywords": ["daycare", "child care", "preschool", "nursery"], "base_risk": "MEDIUM"},
    "713940": {"description": "Fitness and Recreational Sports Centers", "keywords": ["gym", "fitness", "health club", "studio"], "base_risk": "MEDIUM"},
    "721110": {"description": "Hotels (except Casino Hotels) and Motels", "keywords": ["hotel", "motel", "lodging", "inn"], "base_risk": "MEDIUM"},
    "812112": {"description": "Beauty Salons", "keywords": ["salon", "beauty", "hair", "spa"], "base_risk": "LOW"},
    "812910": {"description": "Pet Care (except Veterinary) Services", "keywords": ["pet", "grooming", "boarding", "kennel"], "base_risk": "MEDIUM"},
    "115112": {"description": "Soil Preparation, Planting, and Cultivating", "keywords": ["farming", "agriculture", "crop", "planting"], "base_risk": "MEDIUM"},
}

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def validate_naics(code, predicted_industry: str) -> dict:
    """Validate an LLM-proposed NAICS code against the lookup table."""
    raw = "".join(ch for ch in str(code) if ch.isdigit())
    industry_lc = (predicted_industry or "").lower()

    result = {
        "code": raw or str(code),
        "valid_format": len(raw) == 6,
        "known": False,
        "official_description": None,
        "industry_match": None,
        "expected_risk": None,
        "status": "unverified",
        "notes": [],
    }

    if not result["valid_format"]:
        result["notes"].append("NAICS code is not a 6-digit code.")
        return result

    entry = NAICS_TABLE.get(raw)
    if not entry:
        result["notes"].append("Code not found in reference table — could not verify against a known classification.")
        return result

    result["known"] = True
    result["official_description"] = entry["description"]
    result["expected_risk"] = entry["base_risk"]

    # Industry consistency check via keyword overlap
    haystack = (entry["description"] + " " + " ".join(entry["keywords"])).lower()
    match = any(kw in industry_lc for kw in entry["keywords"]) or any(
        word in haystack for word in industry_lc.split() if len(word) > 3
    )
    result["industry_match"] = match

    if match:
        result["status"] = "verified"
        result["notes"].append(f"Code matches official class: {entry['description']}.")
    else:
        result["status"] = "mismatch"
        result["notes"].append(
            f"Predicted industry '{predicted_industry}' does not align with official class "
            f"'{entry['description']}'. Review recommended."
        )

    return result


def reconcile_risk(llm_risk: str, expected_risk: str) -> dict:
    """Compare the LLM's risk level against the rule-based expected risk for the NAICS class."""
    if not expected_risk or llm_risk not in RISK_ORDER:
        return {"aligned": None, "note": ""}

    diff = RISK_ORDER[llm_risk] - RISK_ORDER[expected_risk]
    if diff == 0:
        return {"aligned": True, "note": f"LLM risk ({llm_risk}) matches rule baseline for this industry."}
    direction = "higher" if diff > 0 else "lower"
    return {
        "aligned": False,
        "note": f"LLM rated {llm_risk}, which is {direction} than the {expected_risk} baseline "
                f"typical for this industry class.",
    }
