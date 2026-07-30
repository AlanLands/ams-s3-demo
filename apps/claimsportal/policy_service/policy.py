from pydantic import BaseModel


class Policy(BaseModel):
    policyNumber: str
    holderName: str
    product: str
    status: str
    coverageLimit: float
