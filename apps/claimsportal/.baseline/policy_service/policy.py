from pydantic import BaseModel


class Policy(BaseModel):
    """A group benefit contract held by a plan sponsor (the employer).

    annualMaximum is the ceiling the plan pays out per member per benefit
    year — the group benefits equivalent of a coverage limit.
    """

    policyNumber: str
    holderName: str  # the plan sponsor holding the group contract
    product: str  # "Health" | "Dental" | "Group Life" | "Disability" | "Critical Illness"
    status: str
    annualMaximum: float
