from pydantic import BaseModel


class Claim(BaseModel):
    id: int
    policyNumber: str
    holderName: str
    amount: float
    description: str
    status: str
    submittedAt: str
