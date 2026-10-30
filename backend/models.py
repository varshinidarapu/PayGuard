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

class KeyCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    label: str = Field(min_length=2, max_length=80)
    expires_in_days: int | None = Field(default=30, ge=1, le=365)

class ClientCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=2, max_length=100)
    client_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{2,39}$')
    key_label: str = Field(default='Initial key', min_length=2, max_length=80)
    expires_in_days: int | None = Field(default=30, ge=1, le=365)
