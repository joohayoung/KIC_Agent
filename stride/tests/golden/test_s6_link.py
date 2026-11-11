"""2026-11-06 결정: 코맥스 주식 담보 해지 공시는 프로젝트에 연결되지 않는다. 캐시된 원문으로 시험하고 claude를 호출하지 않는다."""
import pytest

from agents.overseas_funding.nodes.merge_signals import link_s6, structured_direction
from agents.overseas_funding.nodes.parse_major_events import parse_acquisition_form
from core.clients.dart import get_client
from core.clients.dart_docs import plain_text

pytestmark = pytest.mark.golden
PLEDGE, ACQ, CANCEL_FORM, CANCEL_NOTE, CANCEL_ORIGINAL = "20260203900724", "20260828900607", "20250630900515", "20250630900523", "20241220900448"


def text(no):
    return plain_text(get_client().document(no))


def project(no):
    return {"project_key": "p", "name": parse_acquisition_form(text(no))["name"], "corrections": [], "rcept_nos": [no]}


def test_pledge_release_is_not_linked_to_overseas_project():
    assert link_s6(PLEDGE, text(PLEDGE), [project(ACQ)]) is None


def test_cancellation_links_by_name_field_and_correction_number():
    p = {**project(CANCEL_ORIGINAL), "corrections": [CANCEL_FORM]}
    assert link_s6(CANCEL_NOTE, text(CANCEL_NOTE), [p]) is p and link_s6(CANCEL_FORM, text(CANCEL_FORM), [p]) is p
