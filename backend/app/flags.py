"""The fixed lists of red flags (scam tactics) and green flags (signs of a real contact).

Every explanation screen and the Scam Radar use these ids, so the wording stays the same
everywhere. The AI is only allowed to pick from these lists.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Flag:
    id: str
    kind: str  # "red" or "green"
    label: str
    explanation: str
    category: str  # Scam Radar row this flag counts toward


RED_FLAGS: dict[str, Flag] = {f.id: f for f in [
    Flag("authority", "red", "Authority",
         "They claimed to be someone official, like your bank, so you'd follow orders without checking.",
         "impersonation"),
    Flag("urgency", "red", "Urgency",
         "They rushed you so you'd act before you could think or check.", "urgency"),
    Flag("fear", "red", "Fear",
         "They said something bad would happen, like losing money, to make you panic.", "urgency"),
    Flag("emotional_manipulation", "red", "Emotional manipulation",
         "They used guilt, love or sympathy to push you into helping.", "emotional"),
    Flag("fake_reward", "red", "Fake reward",
         "They offered something too good to be true, like free items or high pay for easy work.",
         "financial"),
    Flag("trust_building", "red", "Trust building",
         "They acted friendly and helpful so you'd lower your guard.", "impersonation"),
    Flag("financial_pressure", "red", "Financial pressure",
         "They asked you to pay a fee or move money. Real jobs and banks don't work that way.",
         "financial"),
    Flag("suspicious_link", "red", "Suspicious link",
         "They sent a link to a lookalike site built to steal logins.", "links_logins"),
    Flag("credential_request", "red", "Credential request",
         "Asking for a one-time code or password is a credential request. Real banks never ask for these.",
         "links_logins"),
    Flag("platform_switch", "red", "Moving the conversation",
         "They tried to move you to another app where there are fewer protections.", "links_logins"),
    Flag("secrecy", "red", "Secrecy",
         "They asked you to keep it secret so no one could warn you.", "emotional"),
    Flag("unusual_payment", "red", "Unusual payment",
         "They wanted gift cards, crypto or a wire transfer, which can't be reversed.", "financial"),
]}

GREEN_FLAGS: dict[str, Flag] = {f.id: f for f in [
    Flag("invites_verification", "green", "Invites verification",
         "They told you to check with them through a number or site you already trust.", "real_contacts"),
    Flag("no_credentials_asked", "green", "Never asks for codes",
         "They never asked for a password or one-time code.", "real_contacts"),
    Flag("no_pressure", "green", "No pressure",
         "No threats or deadlines. You were given time to decide.", "real_contacts"),
    Flag("official_channels", "green", "Official channels",
         "They only used the organization's official website, app or email.", "real_contacts"),
    Flag("checkable_details", "green", "Checkable details",
         "They gave specific details you could confirm on your own.", "real_contacts"),
    Flag("accepts_no", "green", "Accepts no",
         "They stayed calm when you said no or that you'd call back.", "real_contacts"),
    Flag("no_secrecy", "green", "No secrecy",
         "They were fine with you telling family or checking with someone.", "real_contacts"),
    Flag("normal_payment", "green", "Normal payment",
         "Any money went through normal, reversible methods, never gift cards or crypto.", "real_contacts"),
]}

ALL_FLAGS: dict[str, Flag] = {**RED_FLAGS, **GREEN_FLAGS}

# Scam Radar rows, always returned in this order.
RADAR_CATEGORIES: dict[str, str] = {
    "links_logins": "Suspicious links & logins",
    "urgency": "Urgency & fear",
    "impersonation": "Impersonation",
    "financial": "Money & rewards",
    "emotional": "Emotional manipulation",
    "real_contacts": "Recognizing real contacts",
}

# Hand-written tips, one per radar category, so advice is always accurate.
# Picked by the player's biggest weakness in the round.
TIPS: dict[str, tuple[str, str]] = {
    "links_logins": ("links_type_it", "Never log in from a link someone sends you. Type the site address yourself or use the official app."),
    "urgency": ("urgency_pause", "Real deadlines survive a 5-minute pause. If someone says you can't wait to check, that's the reason to check."),
    "impersonation": ("impersonation_callback", "Hang up and call the number on the back of your card or the official website. Caller ID and names can be faked."),
    "financial": ("financial_no_fees", "Real jobs never charge you to start, and no real business asks to be paid in gift cards or crypto."),
    "emotional": ("emotional_code_word", "Agree on a family code word. If a 'relative' in trouble can't say it, call them on their known number."),
    "real_contacts": ("real_verify_anyway", "Even when a message looks real, checking through an official number costs you nothing. Real organizations are glad you did."),
}
