from pydantic import BaseModel, Field, ConfigDict, model_validator

class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    sender_id: int = Field(gt=0)
    receiver_id: int = Field(gt=0)
    amount: int = Field(gt=0, le=100_000_000, description='Integer paise, never floating point')
    currency: str = Field(default='INR', pattern='^INR$')

    @model_validator(mode='after')
    def different_accounts(self):
        if self.sender_id == self.receiver_id:
            raise ValueError('Sender and receiver must differ')
        return self
