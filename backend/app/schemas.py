"""Request and response shapes for every endpoint. These must match api.md."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- Shared ---------------------------------------------------------------


class Message(BaseModel):
    sender: Literal["contact", "player", "notification"]
    text: str
    links: list[str] = []


class Ending(BaseModel):
    code: str
    title: str
    message: str
    is_scam: bool


class FlagInfo(BaseModel):
    id: str
    kind: Literal["red", "green"]
    label: str
    explanation: str


class Hint(BaseModel):
    suspicion: int


# --- Player ---------------------------------------------------------------


class Settings(BaseModel):
    hints: bool = False
    save_conversations: bool = True


class SettingsUpdate(BaseModel):
    hints: bool | None = None
    save_conversations: bool | None = None


class CreatePlayerRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=30)


class PlayerResponse(BaseModel):
    player_id: str
    display_name: str | None
    settings: Settings


class RadarRow(BaseModel):
    category: str
    label: str
    encountered: int
    resisted: int
    percent: int | None


class Badge(BaseModel):
    id: str
    name: str
    description: str
    earned: bool = True


class RadarResponse(BaseModel):
    player_id: str
    display_name: str | None
    level: int
    xp: int
    xp_for_next_level: int
    streak_days: int
    radar: list[RadarRow]
    badges: list[Badge]


# --- Scenarios --------------------------------------------------------------


class ScenarioCard(BaseModel):
    id: str
    title: str
    channel: Literal["sms", "dm", "email", "chat"]
    difficulty: int


class WeaknessPick(BaseModel):
    scenario_id: str
    category: str
    label: str
    percent: int


class ScenarioListResponse(BaseModel):
    scenarios: list[ScenarioCard]
    train_your_weakness: WeaknessPick | None


# --- Round -------------------------------------------------------------------


class Contact(BaseModel):
    name: str
    handle: str


class GiftCard(BaseModel):
    store: str
    amount: int
    code: str


class GamingAccount(BaseModel):
    game: str
    username: str


class FamilyInfo(BaseModel):
    """Family details the player knows, so they can check who they're talking to."""
    relative: str
    parent: str
    parent_phone: str
    memory_question: str
    memory_answer: str


class IdCardExtra(BaseModel):
    """A scenario-specific line on the ID card, e.g. {"label": "Your open support ticket", "value": "#48213"}."""
    label: str
    value: str


class IdCardOut(BaseModel):
    name: str
    email: str
    phone: str
    bank: str
    card_number: str
    card_last4: str
    password: str | None = None
    gift_card: GiftCard | None = None
    gaming_account: GamingAccount | None = None
    family: FamilyInfo | None = None
    extras: list[IdCardExtra] = []


class StartRoundRequest(BaseModel):
    player_id: str
    scenario_id: str
    focus: str | None = None  # Train Your Weakness: a Scam Radar category, e.g. "urgency"


class Focus(BaseModel):
    category: str
    label: str


class StartRoundResponse(BaseModel):
    round_id: str
    scenario_id: str
    channel: str
    difficulty: int
    max_turns: int
    contact: Contact
    id_card: IdCardOut
    opening_message: Message
    suggested_replies: list[str]
    focus: Focus | None = None


class SendMessageRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def trimmed_length(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 500:
            raise ValueError("message must be 1 to 500 characters")
        return v


class TurnResponse(BaseModel):
    blocked: bool = False
    blocked_reason: str | None = None
    turn: int
    max_turns: int
    reply: Message | None = None
    notifications: list[Message] = []
    suggested_replies: list[str] = []
    hint: Hint | None = None
    coach_tip: str | None = None  # only when hints are on; based on what the player did
    ended: bool = False
    ending: Ending | None = None


class CallLine(BaseModel):
    speaker: Literal["official", "player"]  # "official" = the trusted party you called
    text: str


class VerificationCall(BaseModel):
    title: str
    official_name: str  # who "official" is: the bank, the store, a family member
    lines: list[CallLine]


class ActionRequest(BaseModel):
    action: Literal["verify", "hang_up", "report", "trust", "ask_proof", "open_link"]
    link: str | None = None


class ActionResponse(TurnResponse):
    player_message: Message | None = None
    verification_call: VerificationCall | None = None


# --- Result -------------------------------------------------------------------


class PointsLine(BaseModel):
    label: str
    points: int


class TimelineCard(BaseModel):
    turn: int
    flag: FlagInfo
    summary: str
    player_response: Literal["resisted", "fell_for_it", "no_response", "noticed", "missed"]


class Weakness(BaseModel):
    category: str
    label: str


class ScamTwin(BaseModel):
    contact_name: str
    text: str


class Explanation(BaseModel):
    type: Literal["scam_autopsy", "legit_breakdown"]
    timeline: list[TimelineCard]
    good_decisions: list[str]
    mistakes: list[str]
    best_decision: str | None
    biggest_weakness: Weakness | None
    scam_twin: ScamTwin | None = None


class TranscriptEntry(BaseModel):
    index: int
    turn: int
    sender: Literal["contact", "player", "notification"]
    text: str
    flag: FlagInfo | None = None
    note: str | None = None


class Tip(BaseModel):
    id: str
    text: str


class ResultResponse(BaseModel):
    round_id: str
    scenario_id: str
    ending: Ending
    biggest_clue: str
    points: int
    points_breakdown: list[PointsLine]
    xp_earned: int
    explanation: Explanation
    transcript: list[TranscriptEntry]
    tip: Tip
    new_badges: list[Badge]
