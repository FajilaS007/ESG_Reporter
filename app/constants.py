MATERIALITY_WEIGHTS: dict[str, float] = {
    "GRI 305 Emissions": 1.0,
    "GRI 302 Energy": 0.8,
    "GRI 303 Water": 0.7,
    "GRI 304 Biodiversity": 0.7,
    "GRI 306 Waste": 0.6,
    "TCFD Metrics & Targets": 1.0,
    "TCFD Strategy": 0.9,
    "TCFD Risk Management": 0.8,
    "TCFD Governance": 0.6,
}
DEFAULT_MATERIALITY_WEIGHT = 0.5
MAX_DEDUCTION_PER_FINDING = 15
