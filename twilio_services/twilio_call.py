from twilio.rest import Client
import config


client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def make_call(phone_number: str) -> str:
    """
    Initiate an outbound call to a phone number.
    
    Args:
        phone_number: The phone number to call (without country code).
                      Will be prefixed with +91 (India).
    
    Returns:
        The Twilio Call SID.
    """
    call = client.calls.create(
        to=f"+91{phone_number}",
        from_=config.TWILIO_PHONE_NUMBER,
        url=f"{config.SERVER_URL}/voice",
    )
    print(f"✅ [Twilio] Call initiated to +91{phone_number} | SID: {call.sid}")
    return call.sid