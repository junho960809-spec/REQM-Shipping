from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductKnowledge:
    model: str
    product_type: str
    aliases: tuple[str, ...] = ()
    discontinued: bool = False
    replacement_model: str = ""
    capacity_wh: int | None = None
    max_output_w: int | None = None
    supports_power_off_sequence: bool = False


PRODUCTS: dict[str, ProductKnowledge] = {
    "QP1000A": ProductKnowledge("QP1000A", "보조배터리", discontinued=True, replacement_model="QP1000C"),
    "QP2000A": ProductKnowledge("QP2000A", "보조배터리", discontinued=True, replacement_model="QP2000C"),
    "QPD250": ProductKnowledge("QPD250", "충전기", discontinued=True, replacement_model="QPD330"),
    "QPD365": ProductKnowledge("QPD365", "충전기", discontinued=True, replacement_model="QPD365N"),
    "QP1000C": ProductKnowledge(
        "QP1000C", "보조배터리", aliases=("QP1000C1",), capacity_wh=37,
        supports_power_off_sequence=True,
    ),
    "QP2000C": ProductKnowledge(
        "QP2000C", "보조배터리", aliases=("QP2000C1",), capacity_wh=74,
        supports_power_off_sequence=True,
    ),
    "QPD330": ProductKnowledge("QPD330", "충전기", max_output_w=30),
    "QPD365N": ProductKnowledge("QPD365N", "충전기", aliases=("QPD365-N",)),
    "Q1500": ProductKnowledge("Q1500", "무선충전기", aliases=("QWC-Q1500",), max_output_w=15),
    "ACONE": ProductKnowledge("ACONE", "무선충전기", aliases=("QMC-ACONE",)),
    "QM4100": ProductKnowledge("QM4100", "무선충전기", aliases=("QMC-QM4100",)),
    "QMP5": ProductKnowledge("QMP5", "무선충전 보조배터리"),
}


def detect_model(*values: str) -> str:
    source = "\n".join(str(value or "") for value in values).upper()
    candidates: list[tuple[int, str]] = []
    for model, knowledge in PRODUCTS.items():
        for token in (model, *knowledge.aliases):
            if token.upper() in source:
                candidates.append((len(token), model))
    return max(candidates, default=(0, ""))[1]


def get_product_knowledge(model: str) -> ProductKnowledge | None:
    canonical = detect_model(model)
    return PRODUCTS.get(canonical)


def discontinued_replacements() -> dict[str, str]:
    return {
        model: knowledge.replacement_model
        for model, knowledge in PRODUCTS.items()
        if knowledge.discontinued and knowledge.replacement_model
    }
