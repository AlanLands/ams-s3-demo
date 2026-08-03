from pydantic import BaseModel


class Claim(BaseModel):
    """A benefit claim filed by a plan member against a group contract."""

    id: int
    policyNumber: str
    holderName: str  # the plan sponsor on the contract the claim is filed against
    memberId: str
    serviceType: str
    amount: float
    description: str
    status: str
    submittedAt: str
