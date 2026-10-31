"""Phase 5a.2: assign_roles (capability-aware Hungarian, incumbents, stacking, vacancies)."""

import itertools

import numpy as np
import pytest

import cubesat.roles_v2 as roles_v2
from cubesat.roles_v2 import assign_roles

V1 = ["leader", "imager", "imager", "imager", "imager", "downlink"]
DEAD = ("DEAD", False, False)
OK = ("NOMINAL", True, True)


def sats(kinds, incumbents=V1):
    """kinds: one (status, payload_ok, radio_ok) per sat; incumbents: scenario role labels."""
    return [
        {"status": s, "payload_ok": p, "radio_ok": r, "roles": [inc] if inc else []}
        for (s, p, r), inc in zip(kinds, incumbents, strict=True)
    ]


def vacant(out, priority=("downlink", "imager", "leader")):
    return [r for r in priority if not any(r in roles for roles in out)]


def holders(out, role):
    return [i for i, roles in enumerate(out) if role in roles]


def test_v1_roles_map_onto_same_initial_holders():
    out = assign_roles(sats([OK] * 6))
    assert out == [["leader"], ["imager"], ["imager"], ["imager"], ["imager"], ["downlink"]]


def test_four_of_six_dead_keeps_imager():
    out = assign_roles(sats([OK, DEAD, DEAD, DEAD, DEAD, OK]))
    assert out[1:5] == [[], [], [], []]
    assert holders(out, "downlink") == [5]
    assert holders(out, "leader") == [0]
    assert holders(out, "imager") == [0]  # the leader's sat takes the imaging; leader stays
    assert vacant(out) == []


def test_four_dead_with_the_critical_holders_among_the_dead():
    # survivors are two imagers; leader and downlink holders died but keep their stale labels
    kinds = [DEAD, OK, OK, DEAD, DEAD, DEAD]
    inc = ["leader", "imager", "imager", "downlink", "imager", "imager"]
    out = assign_roles(sats(kinds, inc))
    assert holders(out, "downlink") == [1] and holders(out, "imager") == [2]  # downlink: no imaging
    assert holders(out, "leader") == [2]  # stacked on an imager, off the downlink sat
    assert out[0] == out[3] == out[4] == out[5] == []


def test_single_survivor_holds_every_role_it_can_without_crashing():
    for alive in range(6):
        kinds = [OK if i == alive else DEAD for i in range(6)]
        assert assign_roles(sats(kinds))[alive] == ["downlink", "imager", "leader"]
    payload_dead = [("PAYLOAD_FAILED", False, True)] + [DEAD] * 5
    assert assign_roles(sats(payload_dead))[0] == ["downlink", "leader"]
    silent = [("RADIO_SILENT", True, False)] + [DEAD] * 5
    assert assign_roles(sats(silent))[0] == ["spare"]


def test_all_dead_everything_vacant_no_crash():
    out = assign_roles(sats([DEAD] * 6))
    assert out == [[]] * 6 and vacant(out) == ["downlink", "imager", "leader"]
    assert assign_roles([]) == []


def test_leader_stacks_on_an_imager_when_only_two_survive():
    out = assign_roles(sats([OK, DEAD, DEAD, DEAD, DEAD, OK]))
    assert set(out[0]) == {"imager", "leader"} and out[5] == ["downlink"]


def test_incapable_sat_is_never_given_a_role_it_cannot_hold():
    kinds = [OK, ("PAYLOAD_FAILED", False, True), OK, OK, OK, OK]
    out = assign_roles(sats(kinds))
    assert "imager" not in out[1]
    assert holders(out, "imager") == [0, 2, 3, 4]  # the leader-only sat is re-roled to imager
    silent = [OK, OK, OK, OK, OK, ("RADIO_SILENT", True, False)]  # the downlink holder goes mute
    out = assign_roles(sats(silent))
    assert out[5] == ["spare"] and len(holders(out, "downlink")) == 1
    assert 5 not in holders(out, "downlink") + holders(out, "leader")
    silent_leader = [("RADIO_SILENT", True, False)] + [OK] * 5
    out = assign_roles(sats(silent_leader))
    assert holders(out, "leader") and 0 not in holders(out, "leader")


def test_incumbents_keep_their_roles_when_still_capable():
    kinds = [OK, DEAD, OK, OK, OK, OK]  # an imager died: nobody else changes
    out = assign_roles(sats(kinds))
    kept = [out[i] for i in (0, 2, 3, 4, 5)]  # sat 0 (leader only) refills the lost imager seat
    assert kept == [["imager", "leader"], ["imager"], ["imager"], ["imager"], ["downlink"]]
    # a stacked leader on an imager is not moved to a free spare
    inc = [["imager", "leader"], ["downlink"], ["imager"], []]
    s = sats([OK] * 4, [None] * 4)
    for d, r in zip(s, inc, strict=True):
        d["roles"] = r
    assert assign_roles(s) == [["imager", "leader"], ["downlink"], ["imager"], ["spare"]]


def test_exactly_one_leader_and_downlink_for_every_alive_subset():
    for alive in itertools.product([True, False], repeat=6):
        out = assign_roles(sats([OK if a else DEAD for a in alive]))
        want = 1 if any(alive) else 0
        assert len(holders(out, "leader")) == want
        assert len(holders(out, "downlink")) == want
        assert len(holders(out, "imager")) >= want
        assert all(out[i] == [] for i, a in enumerate(alive) if not a)


def test_duplicate_stale_leaders_collapse_to_one():
    inc = ["leader", "leader", "imager", "imager", "imager", "downlink"]
    out = assign_roles(sats([OK] * 6, inc))
    assert holders(out, "leader") == [0]


def test_deterministic_and_input_not_mutated():
    s = sats([OK, DEAD, OK, ("PAYLOAD_FAILED", False, True), OK, OK])
    before = [dict(d, roles=list(d["roles"])) for d in s]
    assert assign_roles(s) == assign_roles(s) and s == before


def test_priority_order_decides_who_gets_a_scarce_sat():
    s = sats([OK, OK], [None, None])
    assert assign_roles(s) == [["downlink"], ["imager", "leader"]]
    swapped = assign_roles(s, ("imager", "downlink", "leader"))
    assert swapped == [["imager", "leader"], ["downlink"]]


def test_no_incumbent_ties_break_to_the_lowest_index():
    s = sats([OK] * 4, [None] * 4)
    assert holders(assign_roles(s), "downlink") == [0]


def test_cost_matrices_are_finite_and_incapable_is_1e6(monkeypatch):
    seen = []
    real = roles_v2.linear_sum_assignment

    def spy(cost):
        seen.append(np.array(cost))
        return real(cost)

    monkeypatch.setattr(roles_v2, "linear_sum_assignment", spy)
    assign_roles(sats([OK, DEAD, DEAD, ("PAYLOAD_FAILED", False, True), OK, OK]))
    assert seen and all(np.isfinite(c).all() for c in seen)
    imager = seen[1]  # priority: downlink, imager, leader
    assert imager[[1, 3], 0] == pytest.approx([1e6, 1e6], abs=1e-3)


def test_unknown_priority_role_is_a_value_error():
    with pytest.raises(ValueError, match="unknown role"):
        assign_roles(sats([OK] * 6), ("pilot",))


def test_a_lost_critical_role_avoids_the_sat_that_already_holds_the_other_one():
    # downlink holder (sat 0) died; sat 1 is the leader, sats 2-3 are free imagers
    inc = [["downlink"], ["imager", "leader"], ["imager"], ["imager"]]
    s = sats([DEAD, OK, OK, OK], [None] * 4)
    for d, r in zip(s, inc, strict=True):
        d["roles"] = r
    out = assign_roles(s)
    assert holders(out, "downlink") == [2] and holders(out, "leader") == [1]


# --- imager seats = min(original count, capable imager-eligible survivors), downlink never images
def test_a_lost_imager_seat_is_refilled_by_a_leader_only_sat_with_a_working_payload():
    out = assign_roles(sats([OK, DEAD, OK, OK, OK, OK]), imager_seats=4)
    assert holders(out, "imager") == [0, 2, 3, 4] and out[0] == ["imager", "leader"]


def test_the_new_downlink_holder_stops_imaging_and_a_leader_only_sat_takes_its_seat():
    out = assign_roles(sats([OK, OK, OK, OK, OK, DEAD]), imager_seats=4)
    assert out == [["imager", "leader"], ["downlink"], ["imager"], ["imager"], ["imager"], []]


def test_seats_are_capped_by_the_eligible_survivors():
    out = assign_roles(sats([OK, DEAD, DEAD, DEAD, DEAD, OK]), imager_seats=4)
    assert holders(out, "imager") == [0] and holders(out, "downlink") == [5]


def test_downlink_holder_images_only_when_it_is_the_sole_imager_capable_sat():
    payload_dead = ("PAYLOAD_FAILED", False, True)
    out = assign_roles(sats([payload_dead, DEAD, DEAD, DEAD, DEAD, OK]), imager_seats=4)
    assert out[5] == ["downlink", "imager"] and out[0] == ["leader"]  # sat 5 is the only imager
    out = assign_roles(sats([OK, DEAD, DEAD, DEAD, DEAD, OK]), imager_seats=4)
    assert "imager" not in out[5]  # a second capable sat exists: the downlink does not image


def test_zero_imager_seats_assigns_no_imager():
    assert holders(assign_roles(sats([OK] * 6), imager_seats=0), "imager") == []


# --- order dependence of the stacking guards (pinned, documented in docs/PHYSICS_V2.md) --------
PERMS = list(itertools.permutations(["downlink", "imager", "leader"]))


def _two_survivors():  # reviewer's counterexample: leader sat, an empty sat, a dead downlink
    inc = [["leader"], [], ["downlink"]]
    s = sats([OK, OK, DEAD], [None] * 3)
    for d, r in zip(s, inc, strict=True):
        d["roles"] = r
    return s


PIN_A = {  # sats [NOMINAL leader, NOMINAL empty, DEAD downlink], imager_seats=1
    ("downlink", "imager", "leader"): [["imager", "leader"], ["downlink"], []],
    ("downlink", "leader", "imager"): [["leader", "imager"], ["downlink"], []],
    ("imager", "downlink", "leader"): [["downlink", "leader"], ["imager"], []],
    ("imager", "leader", "downlink"): [["leader", "downlink"], ["imager"], []],  # pile-up
    ("leader", "downlink", "imager"): [["leader", "imager"], ["downlink"], []],
    ("leader", "imager", "downlink"): [["leader", "downlink"], ["imager"], []],  # pile-up
}
PIN_C = {  # sats [DEAD leader, NOMINAL imager, NOMINAL downlink], imager_seats=1
    p: [[], ["imager", "leader"] if p.index("imager") < p.index("leader") else ["leader", "imager"],
        ["downlink"]]
    for p in PERMS
}


def _case(kinds, inc):
    s = sats(kinds, [None] * len(kinds))
    for d, r in zip(s, inc, strict=True):
        d["roles"] = r
    return s


@pytest.mark.parametrize("perm", PERMS)
def test_two_capable_survivors_pinned_for_every_priority_order(perm):
    a = _case([OK, OK, DEAD], [["leader"], [], ["downlink"]])
    assert assign_roles(a, perm, imager_seats=1) == PIN_A[perm]
    c = _case([DEAD, OK, OK], [["leader"], ["imager"], ["downlink"]])
    assert assign_roles(c, perm, imager_seats=1) == PIN_C[perm]


@pytest.mark.parametrize("perm", PERMS)
def test_three_capable_survivors_keep_their_incumbents_in_every_priority_order(perm):
    b = _case([OK, OK, OK], [["leader"], ["imager"], ["downlink"]])
    assert assign_roles(b, perm, imager_seats=1) == [["leader"], ["imager"], ["downlink"]]


def test_the_default_order_never_piles_leader_and_downlink_on_two_capable_sats():
    for kinds in itertools.product([OK, DEAD], repeat=3):
        if sum(k is OK for k in kinds) != 2:
            continue
        for inc in itertools.permutations([["leader"], ["downlink"], []]):
            out = assign_roles(_case(list(kinds), list(inc)), imager_seats=1)
            assert not any({"leader", "downlink"} <= set(r) for r in out), (kinds, inc, out)
