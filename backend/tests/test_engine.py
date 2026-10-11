import random

import pytest

from app import engine
from app.engine import Analysis, IdCard, PreCheck, RoundState


def make_card(**overrides) -> IdCard:
    fields = dict(
        name="Jordan Rivera",
        email="jordan.rivera@mail.example",
        phone="(555) 010-3382",
        bank="Harbor Point Bank",
        card_number="4000 0037 1822 4417",
        verification_code="482913",
        password="Sunflower#27",
        gift_card_code="PMRT-7Q4K-22XD",
        gaming_username="jordan_builds",
    )
    fields.update(overrides)
    return IdCard(**fields)


def scam_round(**kw) -> RoundState:
    return RoundState(is_scam=True, id_card=make_card(), objective="obtain_verification_code", **kw)


def legit_round(**kw) -> RoundState:
    return RoundState(is_scam=False, id_card=make_card(), objective="confirm_charge", **kw)


def play(state: RoundState, text: str, analysis: Analysis | None = None) -> str | None:
    """One player turn: fixed checks, then the analyzer's judgment."""
    pre = engine.begin_turn(state, text)
    if state.ended:
        return state.ending
    return engine.apply_analysis(state, analysis or Analysis(), pre)


# --- Scam or legit assignment ---------------------------------------------

def test_first_round_is_always_scam():
    assert engine.assign_is_scam([], random.Random(0)) is True


def test_never_more_than_two_legit_in_a_row():
    for seed in range(50):
        assert engine.assign_is_scam([True, False, False], random.Random(seed)) is True


def test_split_is_roughly_65_35():
    rng = random.Random(1)
    picks = [engine.assign_is_scam([True], rng) for _ in range(2000)]
    assert 0.60 < sum(picks) / len(picks) < 0.70


# --- Trap items ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "482913",
    "the code is 482913 ok",
    "482 913",
    "48-29-13",
    "four eight two nine one three",
    "Four Eight Two, nine one three",
])
def test_verification_code_detected_in_any_format(text):
    assert "one-time code" in engine.find_trap_items(text, make_card())


def test_other_trap_items_detected():
    card = make_card()
    assert "full card number" in engine.find_trap_items("4000003718224417", card)
    assert "password" in engine.find_trap_items("my password is sunflower#27", card)
    assert "gift card code" in engine.find_trap_items("pmrt 7q4k 22xd", card)


def test_no_false_trap_on_ordinary_numbers():
    assert engine.find_trap_items("I'm 16 and I have 2 dogs", make_card()) == []


def test_trap_in_scam_round_ends_scammed():
    state = scam_round()
    assert play(state, "ok here: 482913") == "SCAMMED"


def test_trap_in_legit_round_is_serious_mistake_not_ending():
    state = legit_round()
    assert play(state, "482913") is None
    assert state.sensitive_shared == ["one-time code"]
    assert state.mistakes == 1


# --- Real personal data blocker -------------------------------------------

@pytest.mark.parametrize("text", [
    "my ssn is 123-45-6789",
    "123456789",
    "card 4111 1111 1111 1111",
    "call me at 614-292-1234",
])
def test_real_data_is_blocked(text):
    assert engine.blocked_reason(text, make_card()) is not None


@pytest.mark.parametrize("text", [
    "4000 0037 1822 4417",      # the ID card's own number is a trap, not real data
    "(555) 010-3382",           # the ID card's phone
    "call 614-555-0142",        # fictional 555-01xx range
    "4417 482913",              # last four + code, not a phone number
    "I have $486.20",
])
def test_id_card_and_fictional_values_are_not_blocked(text):
    assert engine.blocked_reason(text, make_card()) is None


# --- Minor information -----------------------------------------------------

def test_minor_info_raises_risk_and_costs_points_once():
    state = scam_round()
    play(state, "email me at jordan.rivera@mail.example")
    play(state, "again: jordan.rivera@mail.example")
    assert state.info_shared == ["email"]
    assert state.risk == engine.MINOR_INFO_RISK
    assert [e.points for e in state.score] == [engine.POINTS_MINOR_INFO]
    assert state.mistakes == 2  # the second turn still counts as a mistake


def test_card_last4_counts_as_minor_info():
    state = scam_round()
    play(state, "it ends in 4417")
    assert "card's last four digits" in state.info_shared


# --- Scam endings ----------------------------------------------------------

def test_outsmarted_by_verifying_with_no_mistakes():
    state = scam_round()
    play(state, "who is this?", Analysis(decision_type="challenge"))
    assert engine.apply_action(state, "verify") == "OUTSMARTED"


def test_escaped_by_verifying_after_a_mistake():
    state = scam_round()
    play(state, "jordan.rivera@mail.example")
    assert engine.apply_action(state, "verify") == "ESCAPED"


def test_clean_hang_up_needs_a_recognized_tactic_for_outsmarted():
    state = scam_round()
    engine.record_character_move(state, "urgency", 60)
    play(state, "no", Analysis(decision_type="challenge"))
    assert engine.apply_action(state, "hang_up") == "ESCAPED"

    state = scam_round()
    engine.record_character_move(state, "urgency", 60)
    play(state, "you're rushing me", Analysis(decision_type="challenge", tactic_recognized="urgency"))
    assert engine.apply_action(state, "hang_up") == "OUTSMARTED"


def test_correct_report_scores():
    state = scam_round()
    assert engine.apply_action(state, "report") == "OUTSMARTED"
    assert any(e.points == engine.POINTS_CORRECT_REPORT for e in state.score)


def test_almost_scammed_at_turn_limit():
    state = scam_round(max_turns=3)
    for _ in range(3):
        ending = play(state, "hmm ok", Analysis(decision_type="neutral"))
    assert ending == "ALMOST_SCAMMED"


def test_full_compliance_in_scam_is_scammed():
    state = scam_round(objective_is_payment=True)
    assert play(state, "ok I'll pay", Analysis(decision_type="full_compliance")) == "SCAMMED"
    assert state.risk == engine.PAYMENT_RISK


def test_trusting_a_scammer_is_scammed():
    state = scam_round()
    engine.record_character_move(state, "authority")
    assert engine.apply_action(state, "trust") == "SCAMMED"
    assert state.timeline[0].response == "fell_for_it"


# --- Legit endings ---------------------------------------------------------

def test_verify_legit_is_smart_and_safe():
    state = legit_round()
    assert engine.apply_action(state, "verify") == "SMART_AND_SAFE"


def test_verify_legit_after_sharing_code_is_lucky():
    state = legit_round()
    play(state, "482913")
    assert engine.apply_action(state, "verify") == "LUCKY"


def test_trust_legit_with_green_flag_noticed_is_smart_and_safe():
    state = legit_round()
    engine.record_character_move(state, "invites_verification")
    play(state, "good, you said I can call the number on my card",
         Analysis(decision_type="neutral", flag_noticed="invites_verification"))
    assert engine.apply_action(state, "trust") == "SMART_AND_SAFE"


def test_trust_legit_without_checking_is_lucky():
    state = legit_round()
    assert engine.apply_action(state, "trust") == "LUCKY"


def test_completing_legit_request_ends_round():
    state = legit_round()
    assert play(state, "NO", Analysis(decision_type="full_compliance")) == "LUCKY"


@pytest.mark.parametrize("action", ["hang_up", "report"])
def test_false_alarm(action):
    state = legit_round()
    assert engine.apply_action(state, action) == "FALSE_ALARM"
    assert any(e.points == engine.POINTS_FALSE_ALARM for e in state.score)


def test_legit_turn_limit_is_lucky():
    state = legit_round(max_turns=1)
    assert play(state, "ok", Analysis()) == "LUCKY"


# --- Analyzer claims are checked ------------------------------------------

def test_spotting_a_tactic_only_counts_if_it_was_used():
    state = scam_round()
    engine.record_character_move(state, "urgency")
    play(state, "this feels like fear tactics", Analysis(tactic_recognized="fear"))
    assert state.recognized == []
    play(state, "and you're rushing me", Analysis(tactic_recognized="urgency"))
    assert state.recognized == ["urgency"]


def test_green_flag_only_counts_in_legit_rounds_when_shown():
    state = legit_round()
    play(state, "you gave a case number", Analysis(flag_noticed="checkable_details"))
    assert state.noticed == []


def test_refusing_a_credential_request_earns_bonus():
    state = scam_round()
    engine.record_character_move(state, "credential_request", 70)
    play(state, "No, I won't send a code", Analysis(decision_type="challenge"))
    assert any(e.points == engine.POINTS_REFUSE for e in state.score)
    assert state.timeline[0].response == "resisted"


def test_legit_contact_pressure_is_capped():
    state = legit_round()
    engine.record_character_move(state, "no_pressure", 90)
    assert state.pressure == engine.LEGIT_MAX_PRESSURE


# --- Other rules -----------------------------------------------------------

def test_opening_a_scammers_link_ends_the_round_as_scammed():
    state = scam_round()
    engine.record_character_move(state, "urgency")
    assert engine.open_link(state, "secure-verify-account.example") == "SCAMMED"
    assert state.ending == "SCAMMED" and state.turns == 0  # not a turn, but the round is over
    assert "suspicious_link" in state.tactics_used
    assert {(e.flag_id, e.response) for e in state.timeline} == {("urgency", "fell_for_it"),
                                                               ("suspicious_link", "fell_for_it")}


def test_opening_a_real_contacts_link_is_lucky():
    state = RoundState(is_scam=False, id_card=make_card(), objective="confirm_charge")
    assert engine.open_link(state, "careers.riverside.example") == "LUCKY"
    assert state.ending == "LUCKY" and state.turns == 0 and state.mistakes == 1


def test_cannot_play_after_round_ends():
    state = scam_round()
    engine.apply_action(state, "report")
    with pytest.raises(engine.RoundEndedError):
        engine.begin_turn(state, "hello")


def test_par_bonus_and_points_floor():
    state = scam_round(par_turns=6)
    play(state, "who is this?", Analysis(decision_type="challenge"))
    engine.apply_action(state, "verify")
    # verify 30 + (6 - 1 turns) * 5 under par
    assert state.points == 30 + 5 * 5

    state = legit_round()
    engine.apply_action(state, "report")
    assert state.points == 0  # never negative


def test_xp_and_levels():
    state = scam_round()
    engine.apply_action(state, "report")
    assert engine.xp_for_round(state) == state.points + engine.COMPLETION_BONUS_XP
    assert engine.level_for_xp(0) == 1
    assert engine.level_for_xp(100) == 2
    assert engine.level_for_xp(420) == 3
    assert engine.xp_threshold(4) == 600


def test_no_completion_bonus_when_scammed():
    state = scam_round()
    play(state, "482913")
    assert engine.xp_for_round(state) == state.points


def test_escaped_without_mistakes_gets_its_own_message():
    state = scam_round()
    engine.apply_action(state, "hang_up")
    assert state.ending == "ESCAPED"
    assert engine.ending_message(state) == engine.ESCAPED_CLEAN_MESSAGE

    state = scam_round()
    play(state, "jordan.rivera@mail.example")
    engine.apply_action(state, "hang_up")
    assert engine.ending_message(state) == engine.ENDINGS["ESCAPED"][1]
